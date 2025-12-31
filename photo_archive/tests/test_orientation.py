import unittest

from PIL import Image

from archive_lib.orientation import (
    OrientationInfo,
    ensure_display_orientation,
    extract_orientation_info,
    normalize_orientation,
)


class OrientationHelpersTests(unittest.TestCase):
    def test_extract_orientation_info_handles_missing(self) -> None:
        info = {"data": {"photos_asset": {"orientation": "6", "original_orientation": None}}}
        extracted = extract_orientation_info(info)
        self.assertEqual(extracted.current, 6)
        self.assertIsNone(extracted.original)

    def test_normalize_orientation_filters_values(self) -> None:
        self.assertEqual(normalize_orientation("3"), 3)
        self.assertIsNone(normalize_orientation("not-int"))
        self.assertIsNone(normalize_orientation(42))

    def test_ensure_display_orientation_applies_rotation(self) -> None:
        img = Image.new("RGB", (2, 1))
        img.putpixel((0, 0), (255, 0, 0))
        img.putpixel((1, 0), (0, 0, 255))
        rotated = ensure_display_orientation(img, OrientationInfo(current=8, original=None))
        self.assertEqual(rotated.size, (1, 2))
        pixels = [rotated.getpixel((0, 0)), rotated.getpixel((0, 1))]
        self.assertCountEqual(pixels, [(255, 0, 0), (0, 0, 255)])


if __name__ == "__main__":
    unittest.main()
