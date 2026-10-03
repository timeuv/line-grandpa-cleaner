import os
import cv2
import requests
import numpy as np
from pathlib import Path
from PIL import Image

# Global lazy instances for local model
_ocr_reader = None
_lama_model = None

class SafeSimpleLama:
    """
    Robust LaMa Inpainting wrapper that handles map_location correctly
    on both macOS CPU/MPS and Linux/CUDA without PyTorch CUDA backend crashes.
    """
    def __init__(self, device=None):
        try:
            import torch
        except ImportError:
            raise RuntimeError("PyTorch is not installed in this environment.")

        if device is None:
            if torch.cuda.is_available():
                device = torch.device("cuda")
            else:
                device = torch.device("cpu")
        self.device = device

        from simple_lama_inpainting.utils import download_model
        model_url = os.environ.get(
            "LAMA_MODEL_URL",
            "https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
        )
        model_path = download_model(model_url)
        self.model = torch.jit.load(model_path, map_location=device)
        self.model.eval()
        self.model.to(device)

    def __call__(self, image: Image.Image, mask: Image.Image) -> Image.Image:
        import torch
        from simple_lama_inpainting.utils import prepare_img_and_mask
        orig_w, orig_h = image.size
        img_t, mask_t = prepare_img_and_mask(image, mask, self.device)

        with torch.inference_mode():
            inpainted = self.model(img_t, mask_t)
            cur_res = inpainted[0].permute(1, 2, 0).detach().cpu().numpy()
            cur_res = np.clip(cur_res * 255, 0, 255).astype(np.uint8)
            res_img = Image.fromarray(cur_res)
            return res_img.crop((0, 0, orig_w, orig_h))

def get_ocr_reader():
    """Lazy load EasyOCR reader with Thai and English support (optional)"""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            print("[AI Local] Initializing EasyOCR (Thai & English)...")
            _ocr_reader = easyocr.Reader(['th', 'en'], gpu=False)
            print("[AI Local] EasyOCR initialized successfully.")
        except Exception as e:
            print(f"[AI Warning] EasyOCR not available or failed to load: {e}")
            _ocr_reader = False
    return _ocr_reader

def get_lama_model():
    """Lazy load SafeSimpleLama inpainting model (optional)"""
    global _lama_model
    if _lama_model is None:
        try:
            print("[AI Local] Initializing SafeSimpleLama model...")
            _lama_model = SafeSimpleLama()
            print("[AI Local] SafeSimpleLama model loaded successfully.")
        except Exception as e:
            print(f"[AI Warning] SafeSimpleLama not available or failed to load: {e}")
            _lama_model = False
    return _lama_model

def generate_cloud_text_mask(input_image_path: str, temp_mask_path: str) -> bool:
    """
    Uses Gemini 3.5 Flash Lite (Cloud AI, 0 local RAM) to detect all text boxes
    and creates a binary mask for SnapEdit.
    Returns True if text was detected, False if no text was found.
    """
    gemini_key = os.getenv("GEMINI_API_KEY", "")
    if not gemini_key:
        print("[Mask AI] No GEMINI_API_KEY available. Falling back to local OCR mask...")
        mask = generate_auto_text_mask(input_image_path, dilation_px=12)
        if np.count_nonzero(mask) == 0:
            return False
        Image.fromarray(mask).save(temp_mask_path)
        return True

    try:
        import re
        import json
        import time
        import google.generativeai as genai
        from PIL import ImageDraw

        genai.configure(api_key=gemini_key)
        pil_img = Image.open(input_image_path).convert("RGB")
        w, h = pil_img.size

        prompt = """Locate all text, words, captions, or typography overlaid on this image.
Return ONLY a valid JSON array of objects where each item has "box_2d": [ymin, xmin, ymax, xmax] (normalized from 0 to 1000) and "label": the text.
If there is NO text at all, return []."""

        models_to_try = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
        boxes = []

        for m_name in models_to_try:
            for attempt in range(2):
                try:
                    model = genai.GenerativeModel(m_name)
                    res = model.generate_content([prompt, pil_img])
                    m = re.search(r"\[.*\]", res.text, re.DOTALL)
                    boxes = json.loads(m.group(0)) if m else []
                    if boxes:
                        break
                except Exception as ex:
                    print(f"[Mask AI] {m_name} attempt {attempt+1} error: {ex}")
                    time.sleep(2)
            if boxes:
                break

        if not boxes:
            print("[Mask AI] No text detected in this image.")
            return False

        print(f"[Mask AI] Detected {len(boxes)} text region(s):")
        mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(mask)
        padding = 12

        for item in boxes:
            box = item.get("box_2d")
            if not box or len(box) != 4:
                continue
            ymin, xmin, ymax, xmax = box
            top = max(0, int(ymin * h / 1000) - padding)
            left = max(0, int(xmin * w / 1000) - padding)
            bottom = min(h, int(ymax * h / 1000) + padding)
            right = min(w, int(xmax * w / 1000) + padding)
            draw.rectangle([left, top, right, bottom], fill=255)
            print(f"  - Region: [{left}, {top}, {right}, {bottom}] -> '{item.get('label')}'")

        mask.save(temp_mask_path)
        return True

    except Exception as e:
        print(f"[Mask AI Error] {e}. Trying local fallback mask...")
        mask = generate_auto_text_mask(input_image_path, dilation_px=12)
        if np.count_nonzero(mask) == 0:
            return False
        Image.fromarray(mask).save(temp_mask_path)
        return True

def generate_auto_text_mask(input_image_path: str, dilation_px: int = 10) -> np.ndarray:
    """
    Detects all text regions (Thai/English) and returns a binary mask
    covering the text strokes and drop shadows (if local EasyOCR is available).
    """
    pil_img = Image.open(input_image_path).convert('RGB')
    width, height = pil_img.size
    img_np = np.array(pil_img)
    mask = np.zeros((height, width), dtype=np.uint8)

    reader = get_ocr_reader()
    if not reader:
        return mask

    results = reader.readtext(img_np)
    for bbox, text, prob in results:
        pts = np.array(bbox, dtype=np.int32)
        cv2.fillPoly(mask, [pts], 255)

    if np.count_nonzero(mask) > 0 and dilation_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (dilation_px, dilation_px))
        mask = cv2.dilate(mask, kernel, iterations=1)

    return mask

# =========================================================================
# ENGINE 1: SnapEdit Text Removal API (Cloud AI + Cloud Mask - 1 Credit)
# =========================================================================
def remove_text_snapedit(input_image_path: str, output_image_path: str, api_key: str = None) -> bool:
    """
    Uses Gemini Cloud AI for text detection + SnapEdit Cloud AI for text removal.
    100% Cloud-based: Uses exactly 1 SnapEdit credit, ~50MB RAM, 0 PyTorch in RAM.
    """
    import uuid
    key = api_key or os.getenv("SNAPEDIT_API_KEY", "")
    if not key:
        print("[SnapEdit] No API Key provided.")
        return False

    temp_mask_path = str(Path(output_image_path).parent / f"temp_mask_{uuid.uuid4().hex[:8]}.png")

    try:
        # Step 1: Detect text coordinates via Gemini Cloud AI (Free, 0 RAM)
        has_text = generate_cloud_text_mask(input_image_path, temp_mask_path)
        if not has_text:
            print("[SnapEdit] No text detected in image. Keeping original.")
            Image.open(input_image_path).save(output_image_path, "JPEG", quality=95)
            return True

        # Step 2: Inpaint and remove text via SnapEdit API
        from snapedit import SnapEdit
        client = SnapEdit(api_key=key)

        print("[SnapEdit] Calling SnapEdit remove.text API (1 credit)...")
        res = client.remove.text(input_image=input_image_path, input_mask=temp_mask_path)

        if res.data and res.data[0].url:
            cleaned_url = res.data[0].url
            dl = requests.get(cleaned_url, timeout=30)
            with open(output_image_path, "wb") as f_out:
                f_out.write(dl.content)
            print(f"[SnapEdit] Success! Saved cleaned image to {output_image_path}")
            return True
        else:
            print(f"[SnapEdit Error] No image returned in result: {res}")
            return False

    except Exception as e:
        print(f"[SnapEdit Exception] {e}")
        return False
    finally:
        if os.path.exists(temp_mask_path):
            try:
                os.remove(temp_mask_path)
            except Exception:
                pass

# =========================================================================
# ENGINE 2: ClipDrop Text Removal API (Studio Quality, Commercial SOTA)
# =========================================================================
def remove_text_clipdrop(input_image_path: str, output_image_path: str, api_key: str = None) -> bool:
    """
    Calls ClipDrop Text Removal API (https://clipdrop.co/apis/docs/remove-text)
    """
    key = api_key or os.getenv("CLIPDROP_API_KEY", "")
    if not key:
        print("[ClipDrop] No API Key provided.")
        return False

    url = "https://clipdrop-api.co/remove-text/v1"
    headers = {"x-api-key": key}

    try:
        print("[ClipDrop] Calling ClipDrop Remove-Text API...")
        with open(input_image_path, "rb") as f:
            files = {"image_file": (os.path.basename(input_image_path), f, "image/jpeg")}
            res = requests.post(url, headers=headers, files=files, timeout=40)

        if res.status_code == 200:
            with open(output_image_path, "wb") as f_out:
                f_out.write(res.content)
            print(f"[ClipDrop] Success! Saved cleaned image to {output_image_path}")
            return True
        else:
            print(f"[ClipDrop Error] Status: {res.status_code}, Response: {res.text}")
            return False
    except Exception as e:
        print(f"[ClipDrop Exception] {e}")
        return False

# =========================================================================
# ENGINE 3: Enhanced Local AI with Stroke-Level Masking + LaMa
# =========================================================================
def extract_character_strokes(crop_bgr: np.ndarray) -> np.ndarray:
    """Extracts pixel-level character strokes from a bounding box crop"""
    h, w = crop_bgr.shape[:2]
    if h < 4 or w < 4:
        return np.ones((h, w), dtype=np.uint8) * 255

    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    ksize = max(11, (min(h, w) // 3) * 2 + 1)
    if ksize % 2 == 0:
        ksize += 1

    bg = cv2.medianBlur(gray, min(ksize, 51))
    diff = cv2.absdiff(gray, bg)
    _, thresh = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    edges = cv2.Canny(gray, 50, 150)
    combined = cv2.bitwise_or(thresh, edges)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    stroke_mask = cv2.dilate(combined, kernel, iterations=1)

    if np.count_nonzero(stroke_mask) < (h * w * 0.05):
        return np.ones((h, w), dtype=np.uint8) * 255

    return stroke_mask

def remove_text_local_stroke(input_image_path: str, output_image_path: str) -> bool:
    """Enhanced local AI pipeline with stroke-level masking + LaMa"""
    try:
        pil_img = Image.open(input_image_path).convert('RGB')
        width, height = pil_img.size
        img_np = np.array(pil_img)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

        reader = get_ocr_reader()
        mask = np.zeros((height, width), dtype=np.uint8)
        has_text = False

        if reader:
            print(f"[AI Local] Detecting text in image ({width}x{height})...")
            results = reader.readtext(img_np)
            print(f"[AI Local] Detected {len(results)} text region(s).")

            for bbox, text, prob in results:
                pts = np.array(bbox, dtype=np.int32)
                x_min = max(0, int(np.min(pts[:, 0])))
                x_max = min(width, int(np.max(pts[:, 0])))
                y_min = max(0, int(np.min(pts[:, 1])))
                y_max = min(height, int(np.max(pts[:, 1])))

                if x_max > x_min and y_max > y_min:
                    crop = img_bgr[y_min:y_max, x_min:x_max]
                    stroke_mask = extract_character_strokes(crop)
                    mask[y_min:y_max, x_min:x_max] = cv2.bitwise_or(
                        mask[y_min:y_max, x_min:x_max], stroke_mask
                    )
                    has_text = True
                    print(f"  - Cleaned stroke region for: '{text}' (conf: {prob:.2f})")

        if not has_text:
            print("[AI Local] No text detected. Saving original image.")
            pil_img.save(output_image_path, "JPEG", quality=95)
            return True

        lama = get_lama_model()
        if lama:
            print("[AI Local] Inpainting with LaMa (Stroke-accurate)...")
            mask_pil = Image.fromarray(mask).convert('L')
            cleaned_img = lama(pil_img, mask_pil)
            cleaned_img.save(output_image_path, "JPEG", quality=95)
            print(f"[AI Local] Saved stroke-cleaned image to: {output_image_path}")
            return True
        else:
            print("[AI Local] Inpainting with OpenCV fallback...")
            inpainted = cv2.inpaint(img_bgr, mask, inpaintRadius=5, flags=cv2.INPAINT_NS)
            cv2.imwrite(output_image_path, inpainted)
            print(f"[AI Local] Saved OpenCV inpainted image to: {output_image_path}")
            return True

    except Exception as e:
        print(f"[AI Local Error] {e}")
        import traceback
        traceback.print_exc()
        return False

# =========================================================================
# Unified Dispatcher
# =========================================================================
def remove_text_from_image(
    input_image_path: str,
    output_image_path: str,
    engine: str = "auto"
) -> bool:
    selected_engine = os.getenv("TEXT_REMOVAL_ENGINE", engine).lower()

    if selected_engine == "snapedit":
        if remove_text_snapedit(input_image_path, output_image_path):
            return True
        print("[Fallback] SnapEdit failed, trying local stroke engine...")

    elif selected_engine == "clipdrop":
        if remove_text_clipdrop(input_image_path, output_image_path):
            return True
        print("[Fallback] ClipDrop failed, trying local stroke engine...")

    elif selected_engine == "local_stroke":
        return remove_text_local_stroke(input_image_path, output_image_path)

    # 'auto' mode
    if os.getenv("SNAPEDIT_API_KEY"):
        print("[Engine Auto] Using SnapEdit API...")
        if remove_text_snapedit(input_image_path, output_image_path):
            return True

    if os.getenv("CLIPDROP_API_KEY"):
        print("[Engine Auto] Using ClipDrop API...")
        if remove_text_clipdrop(input_image_path, output_image_path):
            return True

    print("[Engine Auto] Using Enhanced Local Stroke AI...")
    return remove_text_local_stroke(input_image_path, output_image_path)
