import os
import time
import uuid
import hmac
import hashlib
import base64
import requests
import asyncio
from pathlib import Path
from typing import Dict, Any

from fastapi import FastAPI, Request, Header, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv, dotenv_values

from text_cleaner import remove_text_from_image
from conversation_helper import get_grandson_reply, get_sticker_reply

# Load .env file if present
load_dotenv()

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")

def get_base_url() -> str:
    vals = dotenv_values(Path(__file__).parent / ".env")
    url = vals.get("BASE_URL") or os.getenv("BASE_URL", "")
    return url.strip("'\"").rstrip("/")

# Setup static directory for serving processed images
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="LINE Grandpa Photo Cleaner Bot")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

def verify_line_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Verifies that the request came from LINE Developers webhook"""
    if not secret:
        # If secret is not set, allow for development/testing
        return True
    hash_val = hmac.new(secret.encode('utf-8'), body_bytes, hashlib.sha256).digest()
    expected_signature = base64.b64encode(hash_val).decode('utf-8')
    return hmac.compare_digest(expected_signature, signature)

def start_line_loading_animation(chat_id: str):
    """
    Displays native LINE loading animation (three bouncing dots) in grandpa's chat.
    Does NOT consume reply token. Valid up to 60 seconds.
    """
    if not LINE_CHANNEL_ACCESS_TOKEN or not chat_id:
        return
    try:
        url = "https://api.line.me/v2/bot/chat/loading/start"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        payload = {"chatId": chat_id, "loadingSeconds": 60}
        requests.post(url, json=payload, headers=headers, timeout=5)
    except Exception as e:
        print(f"[LINE] Error showing loading animation: {e}")

def reply_line_messages(reply_token: str, messages: list):
    """Sends reply messages using LINE Reply API (100% Free & Unlimited)"""
    if not LINE_CHANNEL_ACCESS_TOKEN or not reply_token:
        return
    try:
        url = "https://api.line.me/v2/bot/message/reply"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        payload = {
            "replyToken": reply_token,
            "messages": messages
        }
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.status_code != 200:
            print(f"[LINE Reply Error] Status: {res.status_code}, Body: {res.text}")
        else:
            print(f"[LINE Reply] Successfully sent {len(messages)} message(s).")
    except Exception as e:
        print(f"[LINE Reply Exception] {e}")

def download_line_image(message_id: str, dest_path: str, max_retries: int = 3) -> bool:
    """
    Downloads an image sent by the user via LINE Data API.
    Includes retry logic and extended timeout to handle large photos,
    original quality files, or temporary LINE CDN propagation delay.
    """
    url = f"https://api-data.line.me/v2/bot/message/{message_id}/content"
    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
    }

    for attempt in range(1, max_retries + 1):
        try:
            print(f"[LINE Download] Attempt {attempt}/{max_retries} for message {message_id}...")
            res = requests.get(url, headers=headers, stream=True, timeout=45)
            if res.status_code == 200:
                with open(dest_path, "wb") as f:
                    for chunk in res.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
                
                # Check that file exists and has data
                if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
                    print(f"[LINE Download] Success! ({os.path.getsize(dest_path)} bytes)")
                    return True
                else:
                    print(f"[LINE Download Warning] Downloaded file is empty, retrying...")
            else:
                print(f"[LINE Download Warning] Status: {res.status_code}, Response: {res.text[:200]}")

        except Exception as e:
            print(f"[LINE Download Exception] Attempt {attempt} error: {e}")

        if attempt < max_retries:
            time.sleep(1.5 * attempt)

    print(f"[LINE Download Error] All {max_retries} download attempts failed.")
    return False

def cleanup_old_files():
    """Removes processed files older than 2 hours to keep disk clean"""
    now = time.time()
    for file_path in STATIC_DIR.glob("*.*"):
        try:
            # Older than 2 hours (7200 seconds)
            if now - file_path.stat().st_mtime > 7200:
                file_path.unlink(missing_ok=True)
        except Exception:
            pass

@app.on_event("startup")
async def startup_event():
    print("=" * 60)
    print("🌸 LINE Grandpa Photo Cleaner Server Started!")
    print(f"📁 Static Directory: {STATIC_DIR}")
    print(f"🌐 BASE_URL: {get_base_url() or '(Not configured yet - set in .env)'}")
    print(f"🔑 LINE Token configured: {'Yes' if LINE_CHANNEL_ACCESS_TOKEN else 'No'}")
    print(f"🔑 LINE Secret configured: {'Yes' if LINE_CHANNEL_SECRET else 'No'}")
    print("=" * 60)

@app.get("/", response_class=HTMLResponse)
async def home():
    """Nice dashboard view"""
    base_url = get_base_url()
    is_ready = bool(LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN and base_url)
    status_color = "#10b981" if is_ready else "#f59e0b"
    status_text = "พร้อมใช้งาน (Online & Ready)" if is_ready else "รอการตั้งค่า LINE Keys & BASE_URL"

    return f"""
    <!DOCTYPE html>
    <html lang="th">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>LINE Grandpa Photo Cleaner AI</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: #0f172a;
                color: #f8fafc;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                margin: 0;
                padding: 20px;
                box-sizing: border-box;
            }}
            .card {{
                background: #1e293b;
                border-radius: 16px;
                padding: 32px;
                max-width: 600px;
                width: 100%;
                box-shadow: 0 10px 25px rgba(0,0,0,0.5);
                border: 1px solid #334155;
            }}
            h1 {{
                margin-top: 0;
                font-size: 24px;
                display: flex;
                align-items: center;
                gap: 10px;
            }}
            .badge {{
                display: inline-block;
                padding: 6px 12px;
                border-radius: 9999px;
                font-size: 13px;
                font-weight: 600;
                background: {status_color}20;
                color: {status_color};
                border: 1px solid {status_color};
                margin-bottom: 20px;
            }}
            .info-item {{
                background: #0f172a;
                padding: 12px 16px;
                border-radius: 8px;
                margin-bottom: 12px;
                font-size: 14px;
                border: 1px solid #334155;
            }}
            .info-item strong {{
                color: #94a3b8;
                display: block;
                font-size: 12px;
                text-transform: uppercase;
                margin-bottom: 4px;
            }}
            code {{
                color: #38bdf8;
                font-family: monospace;
            }}
            .footer {{
                margin-top: 24px;
                font-size: 13px;
                color: #64748b;
                text-align: center;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>🌸 บอทหลานลบข้อความให้คุณตา</h1>
            <div class="badge">{status_text}</div>
            
            <div class="info-item">
                <strong>Webhook URL สำหรับใส่ใน LINE Developers:</strong>
                <code>{base_url}/callback</code>
            </div>

            <div class="info-item">
                <strong>สถานะการเชื่อมต่อ:</strong>
                <div>LINE Access Token: {'✅ ตั้งค่าแล้ว' if LINE_CHANNEL_ACCESS_TOKEN else '❌ ยังไม่ได้ใส่'}</div>
                <div>LINE Channel Secret: {'✅ ตั้งค่าแล้ว' if LINE_CHANNEL_SECRET else '❌ ยังไม่ได้ใส่'}</div>
                <div>Public BASE_URL: {'✅ ' + base_url if base_url else '❌ ยังไม่ได้ใส่'}</div>
                <div>AI Gemini Key: {'✅ เปิดใช้งาน' if os.getenv('GEMINI_API_KEY') else '⚪ ใช้ระบบคำพูดสำเร็จรูปแสนอบอุ่น'}</div>
            </div>

            <div class="info-item">
                <strong>วิธีใช้งาน:</strong>
                <div>คุณตาส่งรูปภาพเข้ามาใน LINE ➡️ บอทตรวจจับข้อความและลบด้วย AI LaMa ➡️ ส่งรูปสะอาดกลับหาคุณตาทันที ❤️</div>
            </div>

            <div class="footer">
                100% Free Forever • Hugging Face Spaces & LINE Official Account
            </div>
        </div>
    </body>
    </html>
    """

def process_image_and_reply(image_id: str, reply_token: str, chat_id: str):
    """Background processor for image inpainting to avoid LINE webhook timeout"""
    base_url = get_base_url()
    unique_id = uuid.uuid4().hex[:10]
    raw_img_path = str(STATIC_DIR / f"raw_{unique_id}.jpg")
    cleaned_img_path = str(STATIC_DIR / f"clean_{unique_id}.jpg")

    # 1. Download image from LINE
    download_success = download_line_image(image_id, raw_img_path)
    if not download_success:
        reply_line_messages(reply_token, [
            {"type": "text", "text": "ขออภัยครับผม หลานดาวน์โหลดรูปภาพไม่สำเร็จ รบกวนลองส่งใหม่อีกครั้งนะครับผม 🙏"}
        ])
        return

    # 2. Inpaint and remove text
    cleaned_success = remove_text_from_image(raw_img_path, cleaned_img_path)

    # Clean up the raw original image
    try:
        os.remove(raw_img_path)
    except Exception:
        pass

    if not cleaned_success or not os.path.exists(cleaned_img_path):
        reply_line_messages(reply_token, [
            {"type": "text", "text": "ขออภัยครับผม หลานพบปัญหาในการประมวลผลภาพ รบกวนลองส่งใหม่อีกรอบนะครับผม ❤️"}
        ])
        return

    # 3. Construct public image URL
    image_url = f"{base_url}/static/clean_{unique_id}.jpg"
    print(f"[LINE Reply] Sending cleaned image back: {image_url}")

    messages = [
        {
            "type": "text",
            "text": "เรียบร้อยแล้วครับผม! หลานลบข้อความในรูปให้สะอาดเรียบร้อยครับ ❤️✨"
        },
        {
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        }
    ]

    reply_line_messages(reply_token, messages)
    cleanup_old_files()

@app.post("/callback")
async def line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(None)
):
    body_bytes = await request.body()
    body_text = body_bytes.decode('utf-8')

    # Signature verification
    if LINE_CHANNEL_SECRET and x_line_signature:
        if not verify_line_signature(body_bytes, x_line_signature, LINE_CHANNEL_SECRET):
            print("[LINE Security] Signature verification failed.")
            raise HTTPException(status_code=400, detail="Invalid signature")

    import json
    try:
        data = json.loads(body_text)
    except Exception:
        return {"status": "ok"}

    events = data.get("events", [])
    for event in events:
        event_type = event.get("type")
        reply_token = event.get("replyToken")
        source = event.get("source", {})
        user_id = source.get("userId", "")

        if event_type == "message":
            msg = event.get("message", {})
            msg_type = msg.get("type")

            # 1. User sends an image
            if msg_type == "image":
                image_id = msg.get("id")
                # Immediately show native loading dots
                start_line_loading_animation(user_id)
                # Dispatch background task to process and reply without timing out webhook
                background_tasks.add_task(process_image_and_reply, image_id, reply_token, user_id)

            # 2. User sends a text message
            elif msg_type == "text":
                user_text = msg.get("text", "")
                reply_text = get_grandson_reply(user_text)
                reply_line_messages(reply_token, [{"type": "text", "text": reply_text}])

            # 3. User sends a sticker
            elif msg_type == "sticker":
                reply_text = get_sticker_reply()
                reply_line_messages(reply_token, [{"type": "text", "text": reply_text}])

            # 4. Other types (audio, video, etc.)
            else:
                reply_line_messages(reply_token, [
                    {"type": "text", "text": "คุณตาส่งรูปภาพที่ต้องการให้หลานลบข้อความมาได้เลยนะคร้าบผม หลานรอทำให้ครับ ❤️"}
                ])

    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 7860))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
