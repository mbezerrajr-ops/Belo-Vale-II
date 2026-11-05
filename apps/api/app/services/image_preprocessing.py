from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()


@dataclass(frozen=True)
class PreprocessedImage:
    content: bytes
    width: int
    height: int
    format: str


def preprocess_image(image_bytes: bytes) -> PreprocessedImage:
    """Normalize EXIF rotation and contrast, and re-encode as JPEG.

    Perspective correction is deferred: it needs page-corner detection that
    the current photo set does not yet reliably support (see design.md's AI
    strategy). Orientation and contrast normalization apply to every photo.
    """
    with Image.open(io.BytesIO(image_bytes)) as opened:
        oriented = ImageOps.exif_transpose(opened)
        if oriented is None:
            oriented = opened
        normalized = ImageOps.autocontrast(oriented.convert("RGB"))

        buffer = io.BytesIO()
        normalized.save(buffer, format="JPEG", quality=90)
        content = buffer.getvalue()

    return PreprocessedImage(
        content=content,
        width=normalized.width,
        height=normalized.height,
        format="JPEG",
    )
