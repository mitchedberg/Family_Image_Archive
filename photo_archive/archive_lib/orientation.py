"""Shared helpers for applying EXIF + Photos orientation metadata."""
from __future__ import annotations

from typing import Any, Dict, NamedTuple, Optional

from PIL import Image, ImageOps

_ORIENTATION_TRANSFORMS = {
    2: (Image.FLIP_LEFT_RIGHT,),
    3: (Image.ROTATE_180,),
    4: (Image.FLIP_TOP_BOTTOM,),
    5: (Image.FLIP_LEFT_RIGHT, Image.ROTATE_90),
    6: (Image.ROTATE_270,),
    7: (Image.FLIP_LEFT_RIGHT, Image.ROTATE_270),
    8: (Image.ROTATE_90,),
}

_TRANSPOSE_INVERSES = {
    Image.FLIP_LEFT_RIGHT: Image.FLIP_LEFT_RIGHT,
    Image.FLIP_TOP_BOTTOM: Image.FLIP_TOP_BOTTOM,
    Image.ROTATE_90: Image.ROTATE_270,
    Image.ROTATE_270: Image.ROTATE_90,
    Image.ROTATE_180: Image.ROTATE_180,
}


class OrientationInfo(NamedTuple):
    current: Optional[int]
    original: Optional[int]


def ensure_display_orientation(
    image: Image.Image,
    orientation: Optional[OrientationInfo],
) -> Image.Image:
    """Return a copy of ``image`` rotated like we do for web_front thumbnails."""

    if image is None:
        raise ValueError("image is required")
    exif_orientation = read_exif_orientation(image)
    img = ImageOps.exif_transpose(image)
    if orientation:
        img = apply_photos_orientation(img, exif_orientation, orientation)
    return img


def read_exif_orientation(image: Image.Image) -> Optional[int]:
    try:
        exif = image.getexif()
    except Exception:  # pragma: no cover - some encoders lack EXIF
        return None
    if not exif:
        return None
    value = exif.get(0x0112)
    return value if isinstance(value, int) else None


def apply_photos_orientation(
    image: Image.Image,
    exif_orientation: Optional[int],
    info: OrientationInfo,
) -> Image.Image:
    target = normalize_orientation(info.current)
    if not target or target == 1:
        return image
    source = exif_orientation or normalize_orientation(info.original)
    if not source or source == 1:
        return _apply_orientation(image, target)
    if source == target:
        return image

    forward = _ORIENTATION_TRANSFORMS.get(source)
    inverse = tuple(_TRANSPOSE_INVERSES[op] for op in forward) if forward else None
    if not forward or not inverse:
        return _apply_orientation(image, target)

    for op in inverse:
        image = image.transpose(op)
    return _apply_orientation(image, target)


def _apply_orientation(image: Image.Image, orientation: int) -> Image.Image:
    ops = _ORIENTATION_TRANSFORMS.get(orientation)
    if not ops:
        return image
    for op in ops:
        image = image.transpose(op)
    return image


def extract_orientation_info(info: Dict[str, Any] | object) -> OrientationInfo:
    data = info.get("data") if isinstance(info, dict) else getattr(info, "data", None)
    if not isinstance(data, dict):
        return OrientationInfo(None, None)
    photos = data.get("photos_asset")
    if not isinstance(photos, dict):
        return OrientationInfo(None, None)
    return OrientationInfo(
        current=normalize_orientation(photos.get("orientation")),
        original=normalize_orientation(photos.get("original_orientation")),
    )


def normalize_orientation(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        orientation = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= orientation <= 8:
        return orientation
    return None

