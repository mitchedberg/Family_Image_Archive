# Backend Reuse Candidates

## 1. Bucket asset resolver
- **Today**
  - Review: `_find_variant_path` (in `photo_archive/cli/review.py`) inspects `sidecar.json` variants to locate `raw_back/proxy_back/ai` files for OCR & full-res streaming.
  - Face Queue: `_bucket_asset_url` + `_asset_exists` (in `photo_archive/cli/faces_queue.py`) build `/buckets/bkt_X/derived/web_*.jpg` URLs.
- **Opportunity**: move into `archive_lib.bucket_assets` with helpers:
  - `get_variant_path(prefix, role)` returning absolute path.
  - `get_web_asset(prefix, role)` returning web URL + existence flag.
- **Benefit**: ensures both servers expose identical logic for front/back detection and reduces drift when negatives/linked backs change.

## 2. Photo context payload
- **Today**
  - Review: dataset rows embed everything (front/AI/back URLs, OCR, voice transcripts) in `review_data.js`.
  - Face Queue: `/api/photo/<bucket>/faces` returns `{bucket_prefix, image_url, has_back, back_url, faces[]}` but lacks OCR/voice.
- **Opportunity**: define canonical JSON schema that both UIs can request (`/api/photo_context/<bucket>`):
  ```json
  {
    "bucket_prefix": "dc77f5…",
    "source": "dad_slides",
    "image": {"front": "/…/web_front.jpg", "ai": "/…/web_ai.jpg", "back": "/…/web_back.jpg"},
    "faces": [... normalized bbox ...],
    "ocr": {"auto_back": "", "auto_front": ""},
    "notes": {"review_note": "", "ocr_status": "draft"},
    "priority": "high"
  }
  ```
- **Benefit**: Photo Tagger could show OCR instantly; Bucket Review could fetch live data instead of baking static JS (enabling incremental updates).

## 3. OCR/Voice loader
- **Today**
  - Review merges `auto_ocr`, `human_ocr`, disk voice transcripts when building dataset.
  - Face Queue doesn’t expose OCR or voice yet but newly built voice recorder lives outside.
- **Opportunity**: Extract `_load_voice_transcripts_from_disk`, `_merge_voice_transcripts`, OCR/human note merge logic into `archive_lib/notes.py` so both servers can import.
- **Benefit**: ensures future Photo Tagger “transcripts” panel matches review UI automatically and prevents double parsing of voice-session format.

## 4. Photo priority store
- **Today**
  - Only Face Queue has `PhotoPriorityStore` that reads/writes `photo_priority.json`.
  - Bucket Review lacks triage but could benefit (e.g., star tough buckets).
- **Opportunity**: move store into shared `archive_lib/photo_priority.py` with CLI helpers, expose same `/api/photo/priority` endpoint from review server or share file watchers.
- **Benefit**: identical JSON schema for both UIs, simpler to build cross-tool dashboards.
