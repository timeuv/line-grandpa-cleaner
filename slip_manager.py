import os
import io
import json
import base64
import requests
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from PIL import Image

DATA_FILE = Path(__file__).parent / "donations.json"
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME = "gemini-3.5-flash-lite"
GEMINI_REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

# Global cache for recent text notes from users (to pair with incoming slips)
_recent_user_notes: Dict[str, Tuple[str, datetime.datetime]] = {}

def load_data() -> Dict[str, Any]:
    """Loads donations data with schema safety"""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[SlipManager] Error reading {DATA_FILE}: {e}")
    
    return {
        "active_campaign": None,
        "history": []
    }

def save_data(data: Dict[str, Any]):
    """Atomically saves donations data"""
    try:
        temp_file = DATA_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.replace(DATA_FILE)
    except Exception as e:
        print(f"[SlipManager] Error saving data: {e}")

def check_auto_archive(data: Dict[str, Any]) -> bool:
    """
    Checks if active campaign has had no activity for over 48 hours (2 days).
    If so, automatically archives it to history.
    """
    camp = data.get("active_campaign")
    if not camp:
        return False
    
    last_str = camp.get("last_updated") or camp.get("created_at")
    if not last_str:
        return False
    
    try:
        last_dt = datetime.datetime.fromisoformat(last_str)
        now_dt = datetime.datetime.now()
        diff = now_dt - last_dt
        if diff.total_seconds() > 48 * 3600:  # 48 hours
            print(f"[SlipManager] Campaign '{camp.get('title')}' inactive for >48h. Auto-archiving.")
            camp["is_active"] = False
            camp["closed_at"] = now_dt.isoformat()
            data.setdefault("history", []).append(camp)
            data["active_campaign"] = None
            save_data(data)
            return True
    except Exception as e:
        print(f"[SlipManager] Error parsing datetime for auto-archive: {e}")
    
    return False

def record_user_recent_text(user_id: str, text: str):
    """Caches recent text message to associate with slips sent right after"""
    if user_id and text:
        _recent_user_notes[user_id] = (text.strip(), datetime.datetime.now())

def get_and_consume_recent_text(user_id: str, max_age_seconds: int = 180) -> Optional[str]:
    """Retrieves recent text note if sent within max_age_seconds"""
    if user_id in _recent_user_notes:
        text, ts = _recent_user_notes[user_id]
        if (datetime.datetime.now() - ts).total_seconds() <= max_age_seconds:
            # Consume so it doesn't apply to subsequent slips
            del _recent_user_notes[user_id]
            return text
        else:
            del _recent_user_notes[user_id]
    return None

def call_gemini_vision(image_path: str, prompt: str) -> Optional[str]:
    """Calls Gemini 3.5 Flash Lite REST API with image and prompt"""
    key = os.getenv("GEMINI_API_KEY", GEMINI_KEY)
    if not key:
        print("[SlipManager] GEMINI_API_KEY is not set.")
        return None

    try:
        # Load and resize image if too large (Gemini needs max ~1024px for fast slip OCR)
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

        url = f"{GEMINI_REST_URL}?key={key}"
        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64_image}}
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }

        res = requests.post(url, json=payload, timeout=25)
        if res.status_code == 200:
            candidates = res.json().get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                if parts:
                    return parts[0].get("text", "")
        else:
            print(f"[SlipManager] Gemini API Error {res.status_code}: {res.text}")
    except Exception as e:
        print(f"[SlipManager] Exception calling Gemini Vision: {e}")

    return None

def analyze_slip_image(image_path: str, user_note: Optional[str] = None) -> Dict[str, Any]:
    """
    Uses Gemini Vision to determine if the image is a bank transfer slip.
    If it is, extracts sender name, amount, bank, date, memo, and occasion thank-you.
    """
    prompt = """
วิเคราะห์ภาพนี้อย่างละเอียด:
1. ภาพนี้คือ 'สลิปการโอนเงินธนาคาร' (Bank transfer slip เช่น กสิกรไทย, ไทยพาณิชย์, กรุงไทย, กรุงเทพ, ออมสิน, ทหารไทยธนชาต, พร้อมเพย์ ฯลฯ) ใช่หรือไม่?
2. หากเป็นสลิป ให้ดึงข้อมูล:
   - "is_slip": true
   - "sender_name": ชื่อผู้โอนเงิน (หากมีคำนำหน้า นาย/นาง/น.ส. ให้ใส่มาด้วย หากชื่อมีดอกจันบัง ให้อ่านเท่าที่เห็น)
   - "amount": จำนวนเงินที่โอน (ตัวเลขทศนิยมหรือจำนวนเต็ม เช่น 500, 1000)
   - "bank": ชื่อธนาคารผู้โอน (เช่น กสิกรไทย, SCB, กรุงไทย ฯลฯ)
   - "transfer_date": วันที่และเวลาโอน (ถ้ามี)
   - "memo": บันทึกช่วยจำในสลิป (ถ้ามี)
   - "occasion_type": ประเภทงานที่น่าจะเกี่ยวข้อง (เช่น "funeral" งานศพ, "merit" งานบุญ/ผ้าป่า, "aid" ช่วยเหลือ/น้ำท่วม/รักษาพยาบาล, "general" ทั่วไป)
   - "thank_you_message": คำขอบคุณสั้นๆ สุภาพ ซาบซึ้ง อ่อนโยน เข้ากับประเภทงาน (เช่น งานศพ: ขอร่วมแสดงความเสียใจและขออนุโมทนาในกุศลจิตครั้งนี้ครับ, งานบุญ: ขออนุโมทนาบุญกับทุกท่านครับ)
3. หากไม่ใช่สลิปโอนเงิน (เช่น ภาพดอกไม้, ภาพวิว, รูปทักทายสวัสดี, รูปบุคคลทั่วไป):
   - ให้ตอบเฉพาะ: {"is_slip": false}

ตอบกลับเป็น JSON ในรูปแบบนี้เท่านั้น:
{
  "is_slip": true/false,
  "sender_name": "ชื่อผู้โอน",
  "amount": 500.0,
  "bank": "ธนาคาร",
  "transfer_date": "วันเวลา",
  "memo": "บันทึกช่วยจำ",
  "occasion_type": "funeral/merit/aid/general",
  "thank_you_message": "คำขอบคุณที่เหมาะสมกับงาน"
}
"""
    if user_note:
        prompt += f"\nหมายเหตุเพิ่มเติมจากผู้ใช้ที่แนบมากับรูป: '{user_note}' (หากมีชื่อคนหรือยอดเงินในข้อความนี้ ให้นำมาประกอบหรือปรับชื่อผู้โอนให้ถูกต้องตามหมายเหตุด้วย)"

    res_json_str = call_gemini_vision(image_path, prompt)
    if not res_json_str:
        return {"is_slip": False}

    try:
        data = json.loads(res_json_str)
        # Type cleanup
        if isinstance(data, dict):
            # Ensure amount is float
            amt = data.get("amount")
            if amt is not None:
                try:
                    if isinstance(amt, str):
                        amt = float(amt.replace(",", "").strip())
                    data["amount"] = float(amt)
                except Exception:
                    data["amount"] = 0.0
            return data
    except Exception as e:
        print(f"[SlipManager] JSON parse error: {e}, raw: {res_json_str}")

    return {"is_slip": False}

def format_campaign_message(campaign: Dict[str, Any], custom_thank_you: Optional[str] = None) -> str:
    """
    Formats the campaign into the exact template requested by the user:
    เงินช่วยเหลืองาน...
    1. [ชื่อ] [ยอดเงิน] บาท
    2. [ชื่อ] [ยอดเงิน] บาท
    ───────────────────
    ยอดเงินรวม: [ยอดเงินรวม] บาท ([จำนวนคน] รายการ)

    [คำขอบคุณที่เหมาะสมกับงานนั้นๆ]
    """
    title = campaign.get("title", "เงินช่วยเหลืองานบุญ / งานช่วยเหลือ")
    entries = campaign.get("entries", [])
    total_amount = sum(e.get("amount", 0.0) for e in entries)

    lines = [f"{title}"]
    
    for idx, item in enumerate(entries, 1):
        name = item.get("name", "ผู้ร่วมทำบุญ")
        amt = item.get("amount", 0.0)
        # Format amount (e.g. 500 or 500.50)
        amt_str = f"{amt:,.0f}" if amt == int(amt) else f"{amt:,.2f}"
        note = item.get("note", "")
        extra_note = f" ({note})" if note else ""
        lines.append(f"{idx}. {name} {amt_str} บาท{extra_note}")

    lines.append("───────────────────")
    total_str = f"{total_amount:,.0f}" if total_amount == int(total_amount) else f"{total_amount:,.2f}"
    lines.append(f"ยอดเงินรวม: {total_str} บาท ({len(entries)} รายการ)")

    # Thank you note
    thank_you = custom_thank_you or campaign.get("thank_you_message")
    if not thank_you:
        # Default respectful thank you
        if "ศพ" in title:
            thank_you = "ขอร่วมแสดงความเสียใจกับครอบครัว และขอขอบคุณทุกท่านที่ร่วมทำบุญอุทิศส่วนกุศลในครั้งนี้ครับ 🙏"
        else:
            thank_you = "ขอขอบคุณและขออนุโมทนาบุญกับทุกท่านที่ร่วมช่วยเหลือในครั้งนี้เป็นอย่างยิ่งครับ 🙏❤️"

    lines.append("")
    lines.append(thank_you)

    return "\n".join(lines)

def process_slip(image_path: str, user_id: str = "") -> Optional[str]:
    """
    Checks image:
    If NOT slip: returns None (so caller can forward to photo text removal).
    If IS slip: records into active campaign and returns formatted summary message.
    """
    user_note = get_and_consume_recent_text(user_id) if user_id else None
    slip_info = analyze_slip_image(image_path, user_note)

    if not slip_info.get("is_slip"):
        return None

    # Load campaign data and handle 48h auto-archive
    data = load_data()
    check_auto_archive(data)

    now_iso = datetime.datetime.now().isoformat()
    camp = data.get("active_campaign")

    # If no active campaign, create one
    if not camp:
        # Try to infer title from slip memo or default
        inferred_title = "เงินช่วยเหลืองานบุญ / งานช่วยเหลือ"
        memo = slip_info.get("memo", "")
        if memo and any(w in memo for w in ["ศพ", "ช่วย", "งาน", "บุญ"]):
            inferred_title = f"เงินช่วยเหลืองาน{memo}"
        elif slip_info.get("occasion_type") == "funeral":
            inferred_title = "เงินช่วยเหลืองานศพ"

        camp = {
            "id": f"camp_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "title": inferred_title,
            "created_at": now_iso,
            "last_updated": now_iso,
            "is_active": True,
            "thank_you_message": slip_info.get("thank_you_message", ""),
            "entries": []
        }
        data["active_campaign"] = camp

    # Prepare entry
    name = slip_info.get("sender_name", "").strip() or "ผู้ร่วมบริจาค"
    # If user provided note like "ของครอบครัวสมชาย", override name
    if user_note:
        if any(w in user_note for w in ["ครอบครัว", "คุณ", "นาย", "นาง", "น.ส."]):
            name = user_note

    entry = {
        "id": len(camp["entries"]) + 1,
        "name": name,
        "amount": slip_info.get("amount", 0.0),
        "bank": slip_info.get("bank", ""),
        "date": slip_info.get("transfer_date", ""),
        "memo": slip_info.get("memo", ""),
        "note": user_note if (user_note and user_note != name) else "",
        "timestamp": now_iso
    }

    camp["entries"].append(entry)
    camp["last_updated"] = now_iso
    if slip_info.get("thank_you_message") and not camp.get("thank_you_message"):
        camp["thank_you_message"] = slip_info.get("thank_you_message")

    save_data(data)

    # Return formatted summary
    return format_campaign_message(camp, slip_info.get("thank_you_message"))

def handle_text_command(text: str, user_id: str = "") -> Optional[str]:
    """
    Checks if incoming text is a command for the donation tracker:
    1. Setting a new campaign topic ("เงินช่วยเหลืองาน...", "เงิน...", "ช่วยเหลือ...", "งาน...")
    2. Reset/New campaign command ("เริ่มงานใหม่", "จบงาน", "ปิดงาน")
    3. Querying summary ("สรุปยอด", "ดูยอด", "ยอดรวม")
    """
    clean_text = text.strip()
    lower = clean_text.lower()

    data = load_data()
    check_auto_archive(data)
    camp = data.get("active_campaign")

    # Command: Manual Close / Finish
    if any(lower == cmd for cmd in ["จบงาน", "ปิดงาน", "เสร็จสิ้น", "ปิดยอด"]):
        if camp:
            summary = format_campaign_message(camp)
            camp["is_active"] = False
            camp["closed_at"] = datetime.datetime.now().isoformat()
            data.setdefault("history", []).append(camp)
            data["active_campaign"] = None
            save_data(data)
            return f"หลานทำการปิดงานสรุปยอดเรียบร้อยแล้วครับผม 🙏✨\n\n{summary}"
        else:
            return "ขณะนี้ยังไม่มีงานบันทึกเงินช่วยเหลือที่เปิดอยู่ครับผม คุณตาสามารถพิมพ์ชื่อหัวข้องานใหม่เพื่อเริ่มบันทึกได้เลยนะคร้าบ ❤️"

    # Command: Start New Campaign
    if any(lower == cmd for cmd in ["เริ่มงานใหม่", "ขึ้นงานใหม่", "เคลียร์ยอด"]):
        if camp:
            camp["is_active"] = False
            camp["closed_at"] = datetime.datetime.now().isoformat()
            data.setdefault("history", []).append(camp)
            data["active_campaign"] = None
            save_data(data)
        return "หลานเปิดสมุดบันทึกเล่มใหม่ให้เรียบร้อยแล้วครับผม! สามารถพิมพ์ชื่อหัวข้องานใหม่ (เช่น 'เงินช่วยเหลืองานศพ...') หรือส่งสลิปมาได้เลยนะคร้าบ ❤️"

    # Command: Query current summary
    if any(cmd in lower for cmd in ["สรุปยอด", "ดูยอด", "ยอดรวม", "รายงานยอด"]):
        if camp and camp.get("entries"):
            return format_campaign_message(camp)
        elif camp:
            return f"เปิดบันทึกหัวข้อ '{camp.get('title')}' ไว้อยู่ครับผม ยังไม่มีสลิปส่งเข้ามา ส่งสลิปเข้ามาได้เลยนะคร้าบ ❤️"
        else:
            return "ขณะนี้ยังไม่มีรายการเงินช่วยเหลือที่เปิดอยู่ครับผม ส่งสลิปหรือพิมพ์ชื่อหัวข้องานเข้ามาได้เลยครับผม 😊"

    # Intent: Setting a new topic or campaign title
    # Detects triggers: starts with 'เงิน', 'งาน', 'ช่วยเหลือ' or has length > 4 with keywords
    if any(k in clean_text for k in ["เงินช่วยเหลือ", "ช่วยเหลืองาน", "เงินทำบุญ", "เงินบริจาค", "งานศพ", "งานบวช", "งานบุญ"]) or \
       (clean_text.startswith("เงิน") and len(clean_text) >= 5) or \
       (clean_text.startswith("งาน") and len(clean_text) >= 5):
        
        # If there was an old campaign with entries, archive it first
        if camp and camp.get("entries"):
            camp["is_active"] = False
            camp["closed_at"] = datetime.datetime.now().isoformat()
            data.setdefault("history", []).append(camp)

        # Set new active campaign
        now_iso = datetime.datetime.now().isoformat()
        new_camp = {
            "id": f"camp_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "title": clean_text,
            "created_at": now_iso,
            "last_updated": now_iso,
            "is_active": True,
            "thank_you_message": "",
            "entries": []
        }
        data["active_campaign"] = new_camp
        save_data(data)

        return (
            f"รับทราบครับผม! หลานเปิดสมุดบันทึกหัวข้อ:\n"
            f"📋 **'{clean_text}'**\n"
            f"ให้เรียบร้อยแล้วครับผม ตาส่งรูปสลิปเข้ามาได้เรื่อยๆ เลยนะคร้าบ หลานจะช่วยรวบรวมรายชื่อและยอดเงินให้อัตโนมัติครับ ❤️✨"
        )

    # Cache recent text for user if it might be a donor name / note
    if user_id:
        record_user_recent_text(user_id, clean_text)

    return None
