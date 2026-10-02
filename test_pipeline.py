"""
Multi-Engine Test Script:
Allows you to compare results across multiple AI text removal engines:
1. Enhanced Local AI (Stroke-Level Masking + LaMa) - 100% Free
2. ClipDrop Text Removal API (Commercial SOTA) - if CLIPDROP_API_KEY is set
3. SnapEdit API (Asian Text Specialist) - if SNAPEDIT_API_KEY is set
"""
import sys
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv

load_dotenv()

from text_cleaner import (
    remove_text_local_stroke,
    remove_text_clipdrop,
    remove_text_snapedit
)

def create_sample_greeting_image(output_path: str):
    """Creates a realistic morning greeting card with Thai text for testing"""
    width, height = 800, 600
    img = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(img)

    # Nature gradient
    for y in range(height):
        r = int(240 - (y / height) * 60)
        g = int(210 - (y / height) * 40)
        b = int(170 + (y / height) * 70)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Decorative lotus / flower shapes
    cx, cy = width // 2, height // 2
    for r in range(140, 40, -20):
        color = (255 - r, 120 + r // 2, 180)
        draw.ellipse([cx - r, cy - r + 30, cx + r, cy + r + 30], fill=color)

    # Thai font
    font_path = "/System/Library/Fonts/Supplemental/Thonburi.ttc"
    if not os.path.exists(font_path):
        font_path = "/System/Library/Fonts/ThonburiUI.ttc"

    try:
        font_large = ImageFont.truetype(font_path, 52)
        font_small = ImageFont.truetype(font_path, 32)
    except Exception:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # Drop shadows & Text
    draw.text((cx - 162, 72), "สวัสดีวันจันทร์", font=font_large, fill=(90, 40, 20))
    draw.text((cx - 160, 70), "สวัสดีวันจันทร์", font=font_large, fill=(255, 255, 255))

    draw.text((cx - 202, 482), "ขอให้มีความสุข สดชื่น แจ่มใส", font=font_small, fill=(70, 30, 20))
    draw.text((cx - 200, 480), "ขอให้มีความสุข สดชื่น แจ่มใส", font=font_small, fill=(255, 245, 220))

    img.save(output_path, "JPEG", quality=95)
    print(f"✅ Created synthetic test image: {output_path}")

def main():
    test_dir = Path(__file__).parent / "test_output"
    test_dir.mkdir(exist_ok=True)

    input_img = sys.argv[1] if len(sys.argv) > 1 else None

    if not input_img:
        sample_path = str(test_dir / "sample_greeting.jpg")
        create_sample_greeting_image(sample_path)
        input_img = sample_path

    print("\n" + "=" * 60)
    print("🚀 MULTI-ENGINE AI TEXT REMOVAL TEST & COMPARISON")
    print(f"📥 Input Image: {input_img}")
    print("=" * 60)

    results = []

    # 1. Enhanced Local Stroke Engine
    print("\n[1/3] Testing Enhanced Local AI (Stroke Mask + LaMa)...")
    local_out = str(test_dir / "sample_local_stroke.jpg")
    if remove_text_local_stroke(input_img, local_out):
        results.append(("Enhanced Local AI", local_out))

    # 2. ClipDrop API
    clipdrop_key = os.getenv("CLIPDROP_API_KEY")
    if clipdrop_key:
        print("\n[2/3] Testing ClipDrop Text Removal API...")
        clipdrop_out = str(test_dir / "sample_clipdrop.jpg")
        if remove_text_clipdrop(input_img, clipdrop_out, clipdrop_key):
            results.append(("ClipDrop API", clipdrop_out))
    else:
        print("\n[2/3] ClipDrop API: ข้าม (ยังไม่ได้ใส่ CLIPDROP_API_KEY ใน .env)")

    # 3. SnapEdit API
    snapedit_key = os.getenv("SNAPEDIT_API_KEY")
    if snapedit_key:
        print("\n[3/3] Testing SnapEdit Text Removal API...")
        snapedit_out = str(test_dir / "sample_snapedit.jpg")
        if remove_text_snapedit(input_img, snapedit_out, snapedit_key):
            results.append(("SnapEdit API", snapedit_out))
    else:
        print("\n[3/3] SnapEdit API: ข้าม (ยังไม่ได้ใส่ SNAPEDIT_API_KEY ใน .env)")

    print("\n" + "=" * 60)
    print("🎉 ผลการทดสอบเสร็จสมบูรณ์:")
    for name, path in results:
        print(f"  • {name}: {path}")
    print("=" * 60)
    print("💡 คุณสามารถเปิดดูและเปรียบเทียบภาพผลลัพธ์ใน Finder ได้เลยครับ")

if __name__ == "__main__":
    main()
