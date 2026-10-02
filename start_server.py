import os
import re
import sys
import time
import subprocess
from pathlib import Path
from dotenv import load_dotenv, set_key

PROJECT_DIR = Path(__file__).parent
ENV_FILE = PROJECT_DIR / ".env"

load_dotenv(ENV_FILE)

def main():
    print("=" * 60)
    print("🌸 Starting LINE Grandpa Photo Cleaner with Cloudflare Tunnel...")
    print("=" * 60)

    # 1. Start Uvicorn Server in background
    venv_python = str(PROJECT_DIR / "venv" / "bin" / "python3")
    uvicorn_cmd = [
        venv_python, "-m", "uvicorn", "app:app",
        "--host", "127.0.0.1", "--port", "7860", "--reload"
    ]
    server_proc = subprocess.Popen(
        uvicorn_cmd,
        cwd=str(PROJECT_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )
    time.sleep(2)
    if server_proc.poll() is not None:
        out, _ = server_proc.communicate()
        print("❌ Server failed to start:")
        print(out)
        return

    print("✅ Local Webhook Server running on http://127.0.0.1:7860")

    # 2. Start Cloudflare Tunnel
    cloudflared_bin = "/opt/homebrew/bin/cloudflared"
    if not os.path.exists(cloudflared_bin):
        cloudflared_bin = "cloudflared"

    tunnel_cmd = [cloudflared_bin, "tunnel", "--url", "http://127.0.0.1:7860"]
    tunnel_proc = subprocess.Popen(
        tunnel_cmd,
        stderr=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        text=True
    )

    public_url = None
    url_pattern = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")

    print("⏳ Acquiring secure public HTTPS tunnel from Cloudflare...")
    for _ in range(30):
        line = tunnel_proc.stderr.readline()
        if not line:
            time.sleep(0.5)
            continue
        match = url_pattern.search(line)
        if match:
            public_url = match.group(0)
            break

    if not public_url:
        print("❌ Could not get public tunnel URL. Check cloudflared output.")
        server_proc.terminate()
        tunnel_proc.terminate()
        return

    # 3. Update BASE_URL in .env
    set_key(str(ENV_FILE), "BASE_URL", public_url)
    os.environ["BASE_URL"] = public_url

    webhook_url = f"{public_url}/callback"

    print("\n" + "=" * 60)
    print("🎉 SYSTEM ONLINE & READY FOR LINE!")
    print(f"🌐 Public Tunnel URL: {public_url}")
    print(f"📌 Webhook URL สำหรับ LINE Developers:")
    print(f"👉 {webhook_url}")
    print("=" * 60)
    print("💡 ขั้นตอนถัดไป:")
    print(f"1. นำ URL ด้านบน ({webhook_url}) ไปใส่ใน LINE Developers ➡️ Messaging API ➡️ Webhook URL")
    print("2. เปิดสวิตช์ 'Use webhook' เป็น ON แล้วกดปุ่ม 'Verify'")
    print("3. ลองส่งรูปภาพเข้าแชท LINE ในมือถือได้ทันที!")
    print("=" * 60)
    print("(กด Ctrl+C เพื่อหยุดการทำงานเมื่อต้องการ)")

    try:
        tunnel_proc.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server and tunnel...")
        server_proc.terminate()
        tunnel_proc.terminate()
        print("👋 Goodbye!")

if __name__ == "__main__":
    main()
