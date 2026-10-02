import os
import json
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import requests

DATA_FILE = Path(__file__).parent / "expenses.json"
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
MODEL_NAME = "gemini-3.5-flash-lite"
GEMINI_REST_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent"

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

def parse_financial_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Parses user text to check if it's an income or expense statement.
    Uses Gemini 3.5 Flash Lite for natural Thai comprehension.
    """
    clean_text = text.strip()
    if not clean_text or len(clean_text) < 2:
        return None

    # Check query commands first (handled separately)
    lower = clean_text.lower()
    if any(q in lower for q in ["สรุปรายรับ", "สรุปรายจ่าย", "ดูรายรับ", "ดูรายจ่าย", "ยอดเงินวันนี้", "ใช้ไปเท่าไหร่", "วันนี้ใช้", "สรุปเงิน", "ดูยอดเงิน", "สมุดเงิน"]):
        return {"action": "summary"}

    if any(q in lower for q in ["ลบรายการล่าสุด", "ลบล่าสุด", "ยกเลิกรายการ"]):
        return {"action": "undo"}

    key = os.getenv("GEMINI_API_KEY", GEMINI_KEY)
    if not key:
        return None

    prompt = f"""
วิเคราะห์ข้อความภาษาไทยนี้ว่าเป็นการ 'บันทึกรายรับ' หรือ 'บันทึกรายจ่าย' ในชีวิตประจำวันหรือไม่:
ข้อความ: "{clean_text}"

เงื่อนไข:
1. หากเป็นข้อความบันทึกการใช้เงินหรือรับเงิน (เช่น "ซื้อกับข้าว 120", "จ่ายค่ายา 350", "ลูกให้เงิน 1000", "ค่ากาแฟ 50", "เติมน้ำมัน 500", "ขายของได้ 300", "กินก๋วยเตี๋ยว 60"):
   - "is_record": true
   - "type": "expense" (รายจ่าย/ซื้อของ/จ่ายเงิน) หรือ "income" (รายรับ/ได้เงิน/ลูกให้)
   - "item": ชื่อรายการสั้นๆ เข้าใจง่าย (เช่น "ซื้อกับข้าว", "ค่ายา", "ลูกให้เงิน", "ค่ากาแฟ")
   - "amount": จำนวนเงินเป็นตัวเลข (float เช่น 120.0, 350.0)
   - "category": หมวดหมู่ เช่น "อาหาร", "สุขภาพ/ยา", "เดินทาง", "ของใช้", "รายได้", "ทำบุญ", "อื่นๆ"
2. หากเป็นข้อความทั่วไปที่ไม่ใช่การบันทึกรายรับรายจ่าย (เช่น "สวัสดี", "ขอบคุณ", "สบายดีไหม", "เงินช่วยเหลืองานศพ..."):
   - "is_record": false

ตอบเป็น JSON เท่านั้น:
{{
  "is_record": true/false,
  "type": "expense" หรือ "income",
  "item": "ชื่อรายการ",
  "amount": 120.0,
  "category": "หมวดหมู่"
}}
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
        print(f"[ExpenseTracker] Parsing error: {e}")

    return None

def analyze_receipt_image(image_path: str) -> Optional[Dict[str, Any]]:
    """
    Analyzes an image to see if it's a store receipt or bill (not a bank transfer slip).
    If it is, extracts the merchant/item and total amount spent.
    """
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

def add_record(entry_type: str, item: str, amount: float, category: str = "ทั่วไป") -> Dict[str, Any]:
    """Adds a record and returns summary for today"""
    data = load_expenses()
    now = datetime.datetime.now()
    
    new_entry = {
        "id": len(data["records"]) + 1,
        "type": entry_type,  # 'income' or 'expense'
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

def handle_expense_text(text: str) -> Optional[str]:
    """
    Processes incoming text for expense tracking:
    - If it's a financial entry -> adds and returns confirmation.
    - If it's a summary request -> returns daily summary.
    - If it's undo -> removes last entry.
    - If not financial -> returns None.
    """
    res = parse_financial_text(text)
    if not res:
        return None

    if res.get("action") == "summary":
        return format_daily_summary_message()

    if res.get("action") == "undo":
        last = undo_last_record()
        if last:
            amt_str = f"{last['amount']:,.0f}" if last['amount'] == int(last['amount']) else f"{last['amount']:,.2f}"
            return f"หลานลบรายการ '{last['item']}' ({amt_str} บาท) ออกให้เรียบร้อยแล้วครับผม! 👍"
        else:
            return "ยังไม่มีรายการให้ลบครับผม 😊"

    if res.get("is_record"):
        entry = add_record(
            entry_type=res.get("type", "expense"),
            item=res.get("item", "รายการทั่วไป"),
            amount=res.get("amount", 0.0),
            category=res.get("category", "ทั่วไป")
        )
        return format_record_success_message(entry)

    return None

def handle_receipt_image(image_path: str) -> Optional[str]:
    """
    Processes image as receipt/bill:
    If it is a receipt, adds as expense and returns confirmation message.
    If not, returns None.
    """
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
