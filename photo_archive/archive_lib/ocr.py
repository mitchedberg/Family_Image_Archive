from __future__ import annotations

from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

try:  # pragma: no cover
    import Vision  # type: ignore
    from Foundation import NSData  # type: ignore
    import objc  # type: ignore
except Exception:  # pragma: no cover
    Vision = None  # type: ignore
    NSData = None  # type: ignore
    objc = None  # type: ignore


def vision_available() -> bool:
    return Vision is not None and NSData is not None


def perform_ocr(image_path: Path) -> str:
    if not vision_available():  # pragma: no cover
        raise RuntimeError(
            "Apple Vision OCR unavailable. Install pyobjc-core and pyobjc-framework-Vision."
        )
    if not image_path.exists():
        raise RuntimeError(f"OCR source missing: {image_path}")
    with _autorelease_pool():
        data = image_path.read_bytes()
        nsdata = NSData.dataWithBytes_length_(data, len(data))
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        request.setUsesLanguageCorrection_(True)
        handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(nsdata, None)
        success, error = handler.performRequests_error_([request], None)
        if not success:
            message = str(error) if error else "Vision OCR failed"
            raise RuntimeError(message)
        lines = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if candidates and len(candidates) > 0:
                text = str(candidates[0].string() or "").strip()
                if text:
                    lines.append(text)
            else:
                value = getattr(observation, "string", lambda: "")()
                if value:
                    lines.append(str(value).strip())
        return "\n".join(filter(None, lines)).strip()


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _autorelease_pool():
    if objc is None:  # pragma: no cover
        yield
        return
    with objc.autorelease_pool():
        yield
