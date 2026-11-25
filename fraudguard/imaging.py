"""Saneado de imágenes subidas: valida formato real, limita tamaño, elimina EXIF/GPS y recodifica."""
from __future__ import annotations

import base64
import io

from PIL import Image, ImageOps, UnidentifiedImageError

Image.MAX_IMAGE_PIXELS = 40_000_000
ALLOWED = {"JPEG", "PNG", "WEBP", "GIF"}
MAX_SIDE = 1568


class BadImage(ValueError):
    pass


def sanitize_image(data: bytes, max_bytes: int = 8 * 1024 * 1024) -> tuple[str, str]:
    """Devuelve (base64, media_type). Siempre JPEG sin metadatos."""
    if not data or len(data) > max_bytes:
        raise BadImage("La imagen está vacía o supera el tamaño máximo.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ALLOWED:
                raise BadImage("Formato de imagen no admitido (usa JPEG, PNG, WebP o GIF).")
            im.load()
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
    except BadImage:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise BadImage("El archivo no es una imagen válida.")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=85)  # sin exif: Pillow no lo escribe salvo que se pase
    return base64.standard_b64encode(out.getvalue()).decode("ascii"), "image/jpeg"
