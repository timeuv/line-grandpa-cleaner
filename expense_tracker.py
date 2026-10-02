import os
import re
import json
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import requests

DATA_FILE = Path(__file__).parent / "expenses.json"
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
# Use the smallest, fastest free model
MODEL_NAME = "gemini-3.5-flash-lite"
GEMINI_REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

# Cache pending bare number confirmations: user_id -> (amount, timestamp)
_pending_number_confirmations: Dict[str, Tuple[float, datetime.datetime]] = {}

def load_expenses() -> Dict[str, Any]:
    """Loads expense records from JSON file"""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[ExpenseTracker] Error loading {DATA_FILE}: {e}")
    
    return {
        "records": []
    }

def save_expenses(data: Dict[str, Any]):
    """Saves expense records safely"""
    try:
        temp_file = DATA_FILE.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_file.replace(DATA_FILE)
    except Exception as e:
        print(f"[ExpenseTracker] Error saving expenses: {e}")

# =========================================================================
# 1. High-Speed Local Thai Regex & Rule Parser (0 API Cost, 0ms Latency)
# =========================================================================
def parse_local_thai_rules(text: str) -> Optional[Dict[str, Any]]:
    """
    Parses Thai text locally without calling external APIs.
    Detects common Thai phrases used by elders:
    - Expenses: ซื้อ, จ่าย, ค่า, กิน, เติม, ทำบุญ
    - Income: ลูกให้, หลานให้, ได้เงิน, บำนาญ, ขาย, เบี้ย
    """
    clean = text.strip()
    
    # 1. Extract amount from string (e.g., "120", "120 บาท", "1,500.50")
    # Matches numbers with optional commas and decimals
    num_match = re.search(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:บาท|บ\.|บ)?', clean)
    if not num_match:
        return None
    
    try:
        raw_num = num_match.group(1).replace(",", "")
        amount = float(raw_num)
        if amount <= 0:
            return None
    except Exception:
        return None

    # Check if text is ONLY a bare number (e.g. "120", "50 บาท")
    # If the rest of the text after removing the number and "บาท" is empty:
    stripped_text = re.sub(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:บาท|บ\.|บ)?', '', clean).strip()
    if not stripped_text:
        return {"action": "ask_bare_number", "amount": amount}

    lower = clean.lower()

    # Rule 1: Income patterns (คนอื่นให้/โอนมาให้เรา)
    is_income = (
        re.search(r'(?:โอนมา|โอนเข้า|เงินเข้า|คืนเงิน)', lower) or
        re.search(r'(?:ลูก|หลาน|เพื่อน|พี่|น้อง|ป้า|ลุง|น้า|อา|แม่|พ่อ|แฟน|คน|เค้า|เขา|ลูกค้า)โอน(?:ให้|มา)?', lower) or
        re.search(r'(?:ลูก|หลาน|เพื่อน|พี่|น้อง|ป้า|ลุง|น้า|อา|แม่|พ่อ|แฟน|คน)ให้', lower) or
        any(kw in lower for kw in ["ได้เงิน", "ได้มา", "เงินเดือน", "บำนาญ", "เบี้ยคนชรา", "เบี้ยผู้สูงอายุ", "ขายได้", "ขายของได้", "รับเงิน", "รับจ้าง", "ปันผล"])
    )

    if is_income:
        item_name = re.sub(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:บาท|บ\.)?$', '', clean).strip()
        if not item_name:
            item_name = clean
        return {
            "is_record": True,
            "type": "income",
            "item": item_name.strip(),
            "amount": amount,
            "category": "รายได้/มีคนให้"
        }

    # Rule 2: Expense patterns (ซื้อ จ่าย โอนออกไป)
    is_expense = (
        re.search(r'^โอนให้|^โอนไป|โอนค่า', lower) or
        any(kw in lower for kw in [
            "ซื้อ", "จ่าย", "ค่า", "กิน", "เติม", "ทำบุญ", "ถวาย",
            "กับข้าว", "ค่ายา", "ค่ารถ", "ค่าไฟ", "ค่าน้ำ", "ค่าหมอ", "กาแฟ", "ก๋วยเตี๋ยว"
        ])
    )

    if is_expense:
        item_name = re.sub(r'(\d+(?:,\d+)*(?:\.\d+)?)\s*(?:บาท|บ\.)?$', '', clean).strip()
        if not item_name:
            item_name = clean
        
        category = "ทั่วไป"
        if any(k in lower for k in ["กับข้าว", "กิน", "กาแฟ", "ก๋วยเตี๋ยว", "อาหาร"]):
            category = "อาหาร"
        elif any(k in lower for k in ["ยา", "หมอ", "โรงพยาบาล"]):
            category = "สุขภาพ/ยา"
        elif any(k in lower for k in ["รถ", "น้ำมัน", "เดินทาง", "แท็กซี่"]):
            category = "เดินทาง"
        elif any(k in lower for k in ["ทำบุญ", "ถวาย", "วัด"]):
            category = "ทำบุญ"

        return {
            "is_record": True,
            "type": "expense",
            "item": item_name.strip(),
            "amount": amount,
            "category": category
        }

    return None

# =========================================================================
# 2. Gemini 3.5 Flash Lite Fallback for complex sentences
# =========================================================================
def parse_financial_text_gemini(text: str) -> Optional[Dict[str, Any]]:
    """Fallback to Gemini 3.5 Flash Lite for natural sentences that regex didn't catch"""
    key = os.getenv("GEMINI_API_KEY", GEMINI_KEY)
    if not key:
        return None

    clean_text = text.strip()
    prompt = f"""
วิเคราะห์ข้อความภาษาไทยนี้ว่าเป็นการ 'บันทึกรายรับ' หรือ 'บันทึกรายจ่าย' หรือไม่:
ข้อความ: "{clean_text}"

หลักการแยกแยะ:
- หากมีคนให้เงินหรือโอนเงินเข้ามา (เช่น "เพื่อนโอนให้ 2000", "ลูกโอนให้ 500", "ป้าให้ 300", "เงินเข้า", "ได้เงิน") ให้ตอบ type: "income" (รายรับ)
- หากเป็นการจ่ายเงิน ซื้อของ หรือโอนเงินออกไป (เช่น "โอนให้เพื่อน 500", "โอนค่าน้ำ", "ซื้อของ", "กินข้าว") ให้ตอบ type: "expense" (รายจ่าย)

ถ้าใช่:
- "is_record": true
- "type": "expense" หรือ "income"
- "item": ชื่อรายการสั้นๆ
- "amount": จำนวนเงิน float
- "category": หมวดหมู่ (อาหาร, สุขภาพ/ยา, เดินทาง, ของใช้, รายได้/มีคนให้, อื่นๆ)
ถ้าไม่ใช่:
- "is_record": false

ตอบเป็น JSON เท่านั้น:
{{"is_record": true/false, "type": "expense/income", "item": "...", "amount": 100.0, "category": "..."}}
"""
    try:
        url = f"{GEMINI_REST_URL}?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json"
            }
        }
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code == 200:
            candidates = res.json().get("candidates", [])
            if candidates:
                part_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed = json.loads(part_text)
                if parsed.get("is_record") and parsed.get("amount", 0) > 0:
                    return parsed
    except Exception as e:
        print(f"[ExpenseTracker] Gemini parser error: {e}")

    return None

# =========================================================================
# 3. Vision Receipt / Bill Parser (Gemini 3.5 Flash Lite)
# =========================================================================
def analyze_receipt_image(image_path: str) -> Optional[Dict[str, Any]]:
    """Analyzes image with Gemini 3.5 Flash Lite to detect receipts/bills"""
    key = os.getenv("GEMINI_API_KEY", GEMINI_KEY)
    if not key:
        return None

    try:
        import io, base64
        from PIL import Image

        with Image.open(image_path) as img:
            img = img.convert("RGB")
            img.thumbnail((1200, 1200), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            b64_image = base64.b64encode(buf.getvalue()).decode("utf-8")

        prompt = """
วิเคราะห์ภาพนี้:
1. ภาพนี้คือ 'ใบเสร็จรับเงิน / ใบเสร็จร้านค้า / บิลค่าใช้จ่าย' (เช่น 7-Eleven, ร้านขายยา, ปั๊มน้ำมัน, ร้านอาหาร, บิลค่าน้ำค่าไฟ) ใช่หรือไม่?
2. หากใช่ ให้ดึงข้อมูล:
   - "is_receipt": true
   - "merchant": ชื่อร้านค้าหรือรายการ (เช่น "7-Eleven", "ร้านขายยา", "ค่าน้ำมัน", "ร้านอาหาร")
   - "total_amount": ยอดเงินรวมสุทธิที่ต้องจ่าย (ตัวเลข float)
   - "category": หมวดหมู่ ("อาหาร", "สุขภาพ/ยา", "ของใช้", "เดินทาง", "อื่นๆ")
3. หากไม่ใช่ใบเสร็จรับเงิน (เช่น สลิปโอนเงินธนาคาร, รูปดอกไม้, รูปคน, รูปวิว):
   - ตอบ: {"is_receipt": false}

ตอบเป็น JSON เท่านั้น:
{
  "is_receipt": true/false,
  "merchant": "ชื่อร้าน",
  "total_amount": 150.0,
  "category": "หมวดหมู่"
}
"""
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
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200:
            candidates = res.json().get("candidates", [])
            if candidates:
                part_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                parsed = json.loads(part_text)
                if parsed.get("is_receipt") and parsed.get("total_amount", 0) > 0:
                    return {
                        "type": "expense",
                        "item": parsed.get("merchant", "ซื้อของตามใบเสร็จ"),
                        "amount": float(parsed.get("total_amount")),
                        "category": parsed.get("category", "ของใช้")
                    }
    except Exception as e:
        print(f"[ExpenseTracker] Receipt vision error: {e}")

    return None

# =========================================================================
# 4. Storage & Formatting
# =========================================================================
def add_record(entry_type: str, item: str, amount: float, category: str = "ทั่วไป") -> Dict[str, Any]:
    """Adds a record and returns summary for today"""
    data = load_expenses()
    now = datetime.datetime.now()
    
    new_entry = {
        "id": len(data["records"]) + 1,
        "type": entry_type,
        "item": item,
        "amount": round(float(amount), 2),
        "category": category,
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M"),
        "timestamp": now.isoformat()
    }
    data["records"].append(new_entry)
    save_expenses(data)
    return new_entry

def undo_last_record() -> Optional[Dict[str, Any]]:
    """Removes the most recent record"""
    data = load_expenses()
    if data.get("records"):
        last = data["records"].pop()
        save_expenses(data)
        return last
    return None

def get_today_summary() -> Tuple[float, float, float, List[Dict[str, Any]]]:
    """Calculates income, expense, balance, and records for today"""
    data = load_expenses()
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    
    today_records = [r for r in data.get("records", []) if r.get("date") == today_str]
    
    total_income = sum(r["amount"] for r in today_records if r["type"] == "income")
    total_expense = sum(r["amount"] for r in today_records if r["type"] == "expense")
    balance = total_income - total_expense
    
    return total_income, total_expense, balance, today_records

def format_record_success_message(entry: Dict[str, Any]) -> str:
    """Formats a warm, elder-friendly confirmation message after adding an entry"""
    total_income, total_expense, balance, today_records = get_today_summary()
    
    is_income = entry["type"] == "income"
    icon = "🟢" if is_income else "🔴"
    type_name = "รายรับ" if is_income else "รายจ่าย"
    amt_str = f"{entry['amount']:,.0f}" if entry['amount'] == int(entry['amount']) else f"{entry['amount']:,.2f}"
    
    today_th = datetime.datetime.now().strftime("%d/%m")
    balance_sign = "+" if balance > 0 else ""
    balance_str = f"{balance_sign}{balance:,.0f}" if balance == int(balance) else f"{balance_sign}{balance:,.2f}"
    inc_str = f"{total_income:,.0f}" if total_income == int(total_income) else f"{total_income:,.2f}"
    exp_str = f"{total_expense:,.0f}" if total_expense == int(total_expense) else f"{total_expense:,.2f}"

    lines = [
        "หลานลงสมุดบันทึกให้เรียบร้อยแล้วครับผม! ❤️",
        "",
        f"📝 รายการ: {entry['item']}",
        f"{icon} {type_name}: {amt_str} บาท",
        "─────────────────────",
        f"📊 ยอดรวมวันนี้ ({today_th}):",
        f"🟢 รายรับ: {inc_str} บาท",
        f"🔴 รายจ่าย: {exp_str} บาท",
        f"💰 คงเหลือวันนี้: {balance_str} บาท",
        "",
        "*(พิมพ์ 'ดูยอดเงิน' เพื่อดูรายการทั้งหมด หรือ 'ลบล่าสุด' เพื่อยกเลิกได้ครับ)*"
    ]
    return "\n".join(lines)

def format_daily_summary_message() -> str:
    """Formats full daily summary with itemized breakdown"""
    total_income, total_expense, balance, today_records = get_today_summary()
    
    if not today_records:
        return (
            "วันนี้ยังไม่มีรายการรายรับรายจ่ายเลยครับผม! 😊\n\n"
            "ตาพิมพ์บอกหลานได้เลยนะคร้าบ เช่น:\n"
            "👉 'ซื้อกับข้าว 120'\n"
            "👉 'ค่ายา 300'\n"
            "👉 'ลูกให้เงิน 1000'\n"
            "หรือส่งรูปใบเสร็จมาให้หลานช่วยบันทึกได้ตลอดเลยครับ ❤️"
        )

    today_th = datetime.datetime.now().strftime("%d/%m/%Y")
    lines = [
        f"📋 สรุปรายรับ-รายจ่ายวันนี้ ({today_th})",
        "─────────────────────"
    ]
    
    for idx, r in enumerate(today_records, 1):
        icon = "🟢" if r["type"] == "income" else "🔴"
        amt_str = f"{r['amount']:,.0f}" if r['amount'] == int(r['amount']) else f"{r['amount']:,.2f}"
        lines.append(f"{idx}. {icon} {r['item']} : {amt_str} บ. ({r['time']})")

    lines.append("─────────────────────")
    inc_str = f"{total_income:,.0f}" if total_income == int(total_income) else f"{total_income:,.2f}"
    exp_str = f"{total_expense:,.0f}" if total_expense == int(total_expense) else f"{total_expense:,.2f}"
    balance_sign = "+" if balance > 0 else ""
    balance_str = f"{balance_sign}{balance:,.0f}" if balance == int(balance) else f"{balance_sign}{balance:,.2f}"

    lines.append(f"🟢 รวมรายรับ: {inc_str} บาท")
    lines.append(f"🔴 รวมรายจ่าย: {exp_str} บาท")
    lines.append(f"💰 ยอดคงเหลือ: {balance_str} บาท")
    
    return "\n".join(lines)

def handle_expense_text(text: str, user_id: str = "") -> Optional[str]:
    """
    Unified text handler:
    1. Checks commands (summary, undo)
    2. Checks pending bare numbers confirmation (if user recently sent a number)
    3. Uses Fast Local Thai Rules (0 API cost, 0ms latency)
    4. If bare number -> Asks user whether it is income or expense
    5. Falls back to Gemini 3.5 Flash Lite if natural text not matched locally
    """
    clean_text = text.strip()
    if not clean_text:
        return None

    lower = clean_text.lower()

    # 1. Summary Query
    if any(q in lower for q in ["สรุปรายรับ", "สรุปรายจ่าย", "ดูรายรับ", "ดูรายจ่าย", "ยอดเงินวันนี้", "ใช้ไปเท่าไหร่", "วันนี้ใช้", "สรุปเงิน", "ดูยอดเงิน", "สมุดเงิน"]):
        return format_daily_summary_message()

    # 2. Undo
    if any(q in lower for q in ["ลบรายการล่าสุด", "ลบล่าสุด", "ยกเลิกรายการ"]):
        last = undo_last_record()
        if last:
            amt_str = f"{last['amount']:,.0f}" if last['amount'] == int(last['amount']) else f"{last['amount']:,.2f}"
            return f"หลานลบรายการ '{last['item']}' ({amt_str} บาท) ออกให้เรียบร้อยแล้วครับผม! 👍"
        else:
            return "ยังไม่มีรายการให้ลบครับผม 😊"

    # 3. Check if user is replying to a pending bare number
    if user_id and user_id in _pending_number_confirmations:
        pending_amt, ts = _pending_number_confirmations[user_id]
        # Valid within 3 minutes
        if (datetime.datetime.now() - ts).total_seconds() <= 180:
            del _pending_number_confirmations[user_id]
            is_income = any(w in lower for w in ["รับ", "รายรับ", "ได้", "บำนาญ", "ลูกให้"])
            entry_type = "income" if is_income else "expense"
            item_name = clean_text if len(clean_text) > 2 else ("รายรับ" if is_income else "รายจ่ายทั่วไป")
            entry = add_record(
                entry_type=entry_type,
                item=item_name,
                amount=pending_amt,
                category="ทั่วไป"
            )
            return format_record_success_message(entry)
        else:
            del _pending_number_confirmations[user_id]

    # 4. Fast Local Thai Rules (0 API Cost)
    local_res = parse_local_thai_rules(clean_text)
    if local_res:
        # If bare number, ask user politely
        if local_res.get("action") == "ask_bare_number":
            amt = local_res.get("amount", 0.0)
            amt_str = f"{amt:,.0f}" if amt == int(amt) else f"{amt:,.2f}"
            if user_id:
                _pending_number_confirmations[user_id] = (amt, datetime.datetime.now())
            return (
                f"ยอด **{amt_str} บาท** นี้ เป็น 'รายรับ' หรือ 'รายจ่าย' ครับผม?\n\n"
                f"👉 ตาพิมพ์บอกหลานสั้นๆ ได้เลยนะคร้าบ เช่น:\n"
                f"- 'รายจ่าย' หรือบอกว่าซื้ออะไร เช่น 'ซื้อกับข้าว'\n"
                f"- 'รายรับ' หรือ 'ลูกให้' ครับผม ❤️"
            )
        
        if local_res.get("is_record"):
            entry = add_record(
                entry_type=local_res.get("type", "expense"),
                item=local_res.get("item", "รายการทั่วไป"),
                amount=local_res.get("amount", 0.0),
                category=local_res.get("category", "ทั่วไป")
            )
            return format_record_success_message(entry)

    # 5. Gemini 3.5 Flash Lite Fallback for complex wording
    gemini_res = parse_financial_text_gemini(clean_text)
    if gemini_res and gemini_res.get("is_record"):
        entry = add_record(
            entry_type=gemini_res.get("type", "expense"),
            item=gemini_res.get("item", "รายการทั่วไป"),
            amount=gemini_res.get("amount", 0.0),
            category=gemini_res.get("category", "ทั่วไป")
        )
        return format_record_success_message(entry)

    return None

def handle_receipt_image(image_path: str) -> Optional[str]:
    """Processes store receipt / bill image using Gemini 3.5 Flash Lite"""
    receipt = analyze_receipt_image(image_path)
    if receipt:
        entry = add_record(
            entry_type="expense",
            item=receipt.get("item", "ซื้อของตามใบเสร็จ"),
            amount=receipt.get("amount", 0.0),
            category=receipt.get("category", "ของใช้")
        )
        return format_record_success_message(entry)
    return None
