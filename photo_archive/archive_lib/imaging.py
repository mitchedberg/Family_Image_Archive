"""Image metadata helpers using Pillow."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dateutil import parser as dateparser
from PIL import Image, UnidentifiedImageError


@dataclass
class ImageMetadata:
    width: Optional[int]
    height: Optional[int]
    exif_datetime: Optional[str]


EXIF_DATETIME_TAGS = {36867, 36868, 306}  # DateTimeOriginal, DateTimeDigitized, DateTime


def probe_image(path: Path) -> ImageMetadata:
    width = height = None
    exif_datetime = None
    try:
        with Image.open(path) as img:
            width, height = img.size
            exif = img.getexif()
            if exif:
                for tag in EXIF_DATETIME_TAGS:
                    value = exif.get(tag)
                    if value:
                        exif_datetime = _normalize_datetime(value)
                        if exif_datetime:
                            break
    except (UnidentifiedImageError, OSError):
        pass
    return ImageMetadata(width=width, height=height, exif_datetime=exif_datetime)


def _normalize_datetime(value: str) -> Optional[str]:
    try:
        return dateparser.parse(value).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def mean_luminance(path: Path) -> Optional[float]:
    """Return normalized mean luminance (0-1) for the image, if readable."""
    try:
        with Image.open(path) as img:
            gray = img.convert("L")
            histogram = gray.histogram()
            total_pixels = sum(histogram)
            if not total_pixels:
                return None
            weighted = sum(i * count for i, count in enumerate(histogram))
            # Normalize to 0-1 range
            return (weighted / total_pixels) / 255.0
    except (UnidentifiedImageError, OSError):
        return None


def dhash(path: Path, size: int = 8) -> Optional[int]:
    """Compute a simple difference hash for perceptual comparisons."""
    try:
        with Image.open(path) as img:
            gray = img.convert("L")
            width = size + 1
            resample_attr = getattr(Image, "Resampling", None)
            resample = resample_attr.LANCZOS if resample_attr else Image.LANCZOS
            resized = gray.resize((width, size), resample)
            pixels = list(resized.getdata())
    except (UnidentifiedImageError, OSError):
        return None

    diff_bits = 0
    bit_index = 0
    for row in range(size):
        row_start = row * width
        for col in range(size):
            left = pixels[row_start + col]
            right = pixels[row_start + col + 1]
            if left > right:
                diff_bits |= 1 << bit_index
            bit_index += 1
    return diff_bits
