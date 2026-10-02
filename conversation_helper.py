import os
import datetime

def get_grandson_reply(user_message: str, user_name: str = "") -> str:
    """
    Generate a warm, caring, respectful reply as a loving grandchild.
    Works universally for grandpa, grandma, or family members.
    Uses Google Gemini if GEMINI_API_KEY is available, otherwise uses smart Thai presets.
    """
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-1.5-flash")

            system_prompt = (
                "คุณคือ 'หลาน' ที่รักและเคารพผู้ใหญ่ในครอบครัวมากๆ (คุณตา/คุณยาย) พูดจาไพเราะ สุภาพ อบอุ่น มีหางเสียง 'ครับ/ครับผม' "
                "ตอบกลับอย่างน่ารัก อบอุ่น สั้นๆ ไม่เกิน 2-3 ประโยค โดยใช้สรรพนามแทนตัวเองว่า 'หลาน' "
                "ไม่จำเป็นต้องระบุชื่อว่าเป็นคุณตาหรือคุณยาย เพื่อให้ใช้ได้ทั้งคุณตาและคุณยาย "
                "และตบท้ายอย่างอ่อนโยนว่าถ้ามีรูปภาพอะไรอยากให้หลานช่วยลบข้อความ ส่งมาให้หลานได้ตลอดเวลาเลยนะครับ"
            )
            response = model.generate_content(f"{system_prompt}\n\nข้อความจากผู้ใหญ่ในครอบครัว: {user_message}")
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"[Conversation] Gemini API error, falling back to smart presets: {e}")

    # Fallback smart preset responses based on keywords and Thai local time
    now_hour = datetime.datetime.now().hour  # Local hour

    msg_lower = user_message.lower() if user_message else ""

    if "ขอบคุณ" in msg_lower or "ขอบใจ" in msg_lower:
        return "ยินดีมากๆ เลยครับผม! หลานยินดีช่วยเสมอครับ ❤️ ถ้ามีรูปอื่นๆ อยากให้หลานช่วยลบข้อความอีก ส่งมาได้เรื่อยๆ เลยนะคร้าบผม"
    elif "กินข้าว" in msg_lower or "ทานข้าว" in msg_lower:
        return "หลานเรียบร้อยแล้วครับผม! ทานให้อร่อยและอิ่มๆ นะครับผม ❤️ มีรูปภาพสวยๆ ส่งมาให้หลานช่วยลบข้อความได้เสมอน้า"
    elif "สวัสดี" in msg_lower:
        if 5 <= now_hour < 11:
            return "สวัสดีตอนเช้าครับผม! ตื่นมารับวันใหม่อย่างสดชื่นนะครับ ทานข้าวเช้าหรือยังครับผม ❤️ ถ้ามีรูปสวัสดีวันใหม่ให้หลานลบข้อความ ส่งมาได้เลยนะคร้าบ"
        elif 11 <= now_hour < 17:
            return "สวัสดีตอนบ่ายครับผม! วันนี้อากาศเป็นอย่างไรบ้างครับ อย่าลืมดื่มน้ำเยอะๆ นะครับผม ❤️ มีรูปอยากให้หลานลบข้อความ ส่งมาได้ตลอดเลยนะครับ"
        else:
            return "สวัสดีตอนเย็นครับผม! วันนี้เหนื่อยไหมครับ พักผ่อนเยอะๆ นะครับผม ❤️ มีรูปอะไรส่งมาให้หลานช่วยลบข้อความได้เสมอนะครับ"
    
    # Default warm fallback
    return "หลานได้รับข้อความแล้วครับผม! ขอให้สุขภาพแข็งแรงและมีความสุขในทุกๆ วันนะครับผม ❤️ ถ้ามีรูปภาพอะไรอยากให้หลานช่วยลบข้อความ ส่งมาให้หลานได้ตลอดเวลาเลยนะครับ"

def get_sticker_reply() -> str:
    """Friendly reply when sending a sticker"""
    return "สติกเกอร์น่ารักมากๆ เลยครับผม! ❤️ หลานพร้อมดูแลเสมอครับ ถ้ามีรูปภาพอยากให้ช่วยลบข้อความ ส่งมาให้หลานได้เลยนะครับผม 😊"
