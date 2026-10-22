"""پردازش تصویر (معادل نودهای Edit Image)."""

import io

from PIL import Image, ImageOps

from aniwall import config

Image.MAX_IMAGE_PIXELS = 400_000_000
_PHOTO_MAX_BYTES = 9_500_000


def _to_rgb(src: Image.Image) -> Image.Image:
    im = ImageOps.exif_transpose(src)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        return bg
    if im.mode != "RGB":
        return im.convert("RGB")
    return im


def _open_rgb(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as src:
        return _to_rgb(src).copy()


def _jpeg_bytes(im: Image.Image, quality: int) -> bytes:
    out = io.BytesIO()
    im.save(out, "JPEG", quality=quality)
    return out.getvalue()


def _fit_box(im: Image.Image, max_sum: int, max_side: int) -> Image.Image:
    w, h = im.size
    if w <= 0 or h <= 0:
        raise ValueError("ابعاد تصویر نامعتبر است")
    scale = 1.0
    if w + h > max_sum:
        scale = min(scale, max_sum / (w + h))
    if w * scale > max_side:
        scale = min(scale, max_side / w)
    if h * scale > max_side:
        scale = min(scale, max_side / h)
    if scale >= 1.0:
        return im
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im.resize((nw, nh), Image.LANCZOS)


def _shrink_under(im: Image.Image, limit: int, quality: int) -> bytes:
    blob = _jpeg_bytes(im, quality)
    while len(blob) > limit and quality > 45:
        quality -= 10
        blob = _jpeg_bytes(im, quality)
    while len(blob) > limit:
        w, h = im.size
        if min(w, h) < 400:
            break
        im = im.resize((max(1, w * 3 // 4), max(1, h * 3 // 4)), Image.LANCZOS)
        blob = _jpeg_bytes(im, max(quality, 70))
    return blob


def to_jpeg(data: bytes, max_side: int = 1920, quality: int = 85) -> bytes:
    """ریسایز onlyIfLarger داخل کادر max_side×max_side + خروجی JPEG."""
    im = _open_rgb(data)
    im.thumbnail((max_side, max_side), Image.LANCZOS)
    return _jpeg_bytes(im, quality)


def fit_photo(data: bytes) -> bytes:
    """JPEG مناسب sendPhoto تلگرام (ابعاد + سقف حجم)."""
    im = _fit_box(_open_rgb(data), config.TG_MAX_SUM, config.TG_MAX_SIDE)
    blob = _shrink_under(im, _PHOTO_MAX_BYTES, 85)
    if len(blob) > 10_000_000:
        raise ValueError("عکس بعد از فشرده‌سازی هم برای تلگرام بزرگ است")
    return blob


def fit_document(data: bytes, ext: str) -> tuple[bytes, str]:
    """فایل اصلی اگر زیر سقف سند تلگرام باشد؛ وگرنه JPEG فشرده."""
    ext = (ext or "jpg").lower()
    if ext == "jpeg":
        ext = "jpg"
    if ext in ("jpg", "png", "webp") and len(data) <= config.TG_DOC_MAX_BYTES:
        return data, ext
    im = _open_rgb(data)
    blob = _shrink_under(im, config.TG_DOC_MAX_BYTES, 90)
    if len(blob) > config.TG_DOC_MAX_BYTES:
        raise ValueError("سند از سقف ۵۰MB تلگرام بزرگ‌تر است")
    return blob, "jpg"
