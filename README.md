# 🌸 LINE Photo Cleaner Bot (บอทหลานช่วยลบข้อความในรูป)

ระบบ **LINE Official Account + AI ลบข้อความในรูปภาพสำหรับคุณตาคุณยายและคนในครอบครัว**:
- **โหมด Multi-Engine**: เลือกระหว่าง AI คุณภาพสูงระดับสตูดิโอ (ClipDrop / SnapEdit) หรือระบบฟรีในเครื่อง (Enhanced Local AI)
- **ใช้งานง่ายที่สุดสำหรับผู้ใหญ่**: ส่งรูปภาพอะไรมา (ภาพสวัสดีวันจันทร์, ดอกไม้, คำคม) บอทจะลบข้อความออกให้เนียนกริบอัตโนมัติ
- **เสมือนมีหลานดูแล**: มีสถานะ Loading กำลังทำ และตอบกลับด้วยคำพูดอบอุ่น สุภาพ เสมือนหลานคนโปรด
- **คุยเล่นได้**: หากส่งสติกเกอร์ หรือพิมพ์ทักทาย บอทจะตอบกลับอย่างอบอุ่นและสุภาพครับผม

---

## 🏆 เปรียบเทียบ AI Engines สำหรับลบข้อความ

| Engine | ระดับความเนียน | ค่าใช้จ่าย | จุดเด่น |
|---|---|---|---|
| **ClipDrop Text Removal API** *(แนะนำ)* | ⭐⭐⭐⭐⭐ (10/10) | ฟรี 100 เครดิตแรก | คุณภาพเนียนระดับสตูดิโอ ลบสะอาด 100% ไม่ทิ้งรอยเบลอ |
| **SnapEdit API** | ⭐⭐⭐⭐⭐ (9.5/10) | มี Free Tier | ออกแบบมาสำหรับภาษาไทยและสไตล์ภาพเอเชียโดยเฉพาะ |
| **Enhanced Local AI (Stroke Mask + LaMa)** | ⭐⭐⭐⭐ (8/10) | **ฟรี 100% ตลอดชีพ** | เจาะเฉพาะเส้นตัวอักษร ไม่กินพื้นที่พื้นหลัง รันบน Mac หรือ Hugging Face ได้ฟรี |

> **โหมด `auto` (ค่าเริ่มต้น)**: หากคุณใส่ `CLIPDROP_API_KEY` ใน `.env` หรือ Hugging Face Secrets ระบบจะใช้ ClipDrop เพื่อความเนียนสูงสุด ถ้าไม่มีจะสลับมาใช้ Enhanced Local AI ให้อัตโนมัติ

---

## 🔑 วิธีรับ API Key ฟรีสำหรับทดสอบ

### 1. ClipDrop API (เนียนที่สุดในวงการ)
1. ไปที่ [clipdrop.co/apis](https://clipdrop.co/apis)
2. สมัครสมาชิก (Google Login ได้)
3. เข้าไปที่หน้า Dashboard เพื่อคัดลอก `API Key` (มีเครดิตฟรีให้ทดสอบ 100 รูป)
4. นำมาใส่ในไฟล์ `.env` ช่อง `CLIPDROP_API_KEY=`

### 2. SnapEdit API
1. ไปที่ [developer.snapedit.app](https://developer.snapedit.app)
2. สมัครและสร้าง API Key
3. นำมาใส่ในไฟล์ `.env` ช่อง `SNAPEDIT_API_KEY=`

---

## 🧪 วิธีทดสอบและเปรียบเทียบภาพในเครื่อง Mac

คุณสามารถทดสอบเปรียบเทียบทุก Engine ได้ทันทีด้วยคำสั่งเดียว:

```bash
cd /Users/time/.gemini/antigravity-ide/scratch/line-grandpa-photo-cleaner
source venv/bin/activate

# ทดสอบกับภาพสังเคราะห์ตัวอย่าง
python3 test_pipeline.py

# หรือทดสอบกับรูปภาพของคุณตาจริงๆ ในเครื่อง
python3 test_pipeline.py /path/to/grandpa_photo.jpg
```

ผลลัพธ์จะถูกเซฟแยกไฟล์ไว้ในโฟลเดอร์ `test_output/` เพื่อให้คุณเปิดดูเปรียบเทียบใน Finder ได้ทันที:
- `sample_original.jpg` (ภาพต้นฉบับ)
- `sample_local_stroke.jpg` (ผลลัพธ์จาก AI ในเครื่องแบบเจาะเส้น)
- `sample_clipdrop.jpg` (ผลลัพธ์จาก ClipDrop API - ถ้าใส่คีย์)
- `sample_snapedit.jpg` (ผลลัพธ์จาก SnapEdit API - ถ้าใส่คีย์)

---

## 🚀 วิธีนำขึ้น Hugging Face Spaces (ฟรี 24 ชม.)

1. สร้าง Space บน [huggingface.co](https://huggingface.co) (เลือก **Docker SDK**, สเปกฟรี RAM 16GB)
2. อัปโหลดไฟล์หลักขึ้นไป:
   - `Dockerfile`
   - `requirements.txt`
   - `app.py`
   - `text_cleaner.py`
   - `conversation_helper.py`
3. ในหน้า Space ไปที่ **Settings** ➡️ **Variables and secrets** แล้วใส่:
   - `LINE_CHANNEL_SECRET`: Channel Secret จาก LINE
   - `LINE_CHANNEL_ACCESS_TOKEN`: Channel Access Token จาก LINE
   - `BASE_URL`: `https://<username>-<space-name>.hf.space`
   - `CLIPDROP_API_KEY`: *(ใส่ถ้าต้องการใช้ ClipDrop เพื่อความเนียนสูงสุด)*
   - `GEMINI_API_KEY`: *(ใส่ถ้าต้องการให้บอทคุยเป็นธรรมชาติ)*
