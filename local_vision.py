"""Local Vision v2 — image analysis + OCR.

Stack:
  - BLIP: image captioning (what's in the image)
  - easyocr: text extraction (what does it say)
  - Combined: describe what the image shows AND what text it contains

$0 per call. Offline. CPU-only.
"""

from pathlib import Path

_BLIP_LOADED = False
_OCR_LOADED = False


def _blip_caption(image_path: str) -> str:
    """Get a short caption of the image content."""
    global _BLIP_LOADED
    try:
        from PIL import Image
        from transformers import BlipProcessor, BlipForConditionalGeneration

        if not _BLIP_LOADED:
            global _processor, _model
            _processor = BlipProcessor.from_pretrained(
                "Salesforce/blip-image-captioning-base",
                cache_dir="/opt/data/.cache/huggingface",
            )
            _model = BlipForConditionalGeneration.from_pretrained(
                "Salesforce/blip-image-captioning-base",
                cache_dir="/opt/data/.cache/huggingface",
            )
            _BLIP_LOADED = True

        image = Image.open(image_path).convert("RGB")
        inputs = _processor(image, return_tensors="pt")
        out = _model.generate(**inputs, max_length=80)
        return _processor.decode(out[0], skip_special_tokens=True)
    except Exception as e:
        return f"(caption unavailable: {e})"


def _ocr_text(image_path: str) -> str:
    """Extract text from image using easyocr."""
    global _OCR_LOADED
    try:
        import easyocr
        if not _OCR_LOADED:
            global _reader
            _reader = easyocr.Reader(["ch_sim", "en"], gpu=False)
            _OCR_LOADED = True

        results = _reader.readtext(image_path, detail=0)
        return "\n".join(results) if results else "(no text found)"
    except Exception as e:
        return f"(OCR unavailable: {e})"


def analyze_image(image_path: str) -> str:
    """Full analysis: caption + OCR text.

    Returns a combined description suitable for agent context.
    """
    caption = _blip_caption(image_path)
    text = _ocr_text(image_path)

    parts = [f"[Image: {caption}]"]
    if text and text != "(no text found)" and "unavailable" not in text:
        parts.append(f"[Text content:\n{text}\n]")

    return "\n".join(parts)
