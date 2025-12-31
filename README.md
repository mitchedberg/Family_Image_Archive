# Family Image Archive Backend

## Overview
Preservation-focused pipeline with read-only TIFF sources, bucketized manifest on SSD, and Apple Photos as a published view. Originals stay where they are; we work off staging copies in `01_INBOX/` and store canonical metadata + manifests in `02_WORKING_BUCKETS/`.

## Hard Constraints
1. Never modify originals (TIFF fronts/backs). Treat inputs as read-only.
2. All scripts must be idempotent and safe to re-run.
3. Bucket identity: `bucket_id = sha256(raw_front TIFF)` when available; fallback to best available front file.
4. File roles per bucket: `raw_front`, `proxy_front`, `ai_front_v1`, `raw_back`, `proxy_back`.
5. Provenance captured via `source` (mom|dad|uncle|other).
6. Preserve folder semantics via `original_relpath` + `original_filename` metadata.
7. Apple Photos is just a published view; we export preferred fronts only and embed `bucket:<short_id>` keywords for round-tripping.

## Directory Layout
```
01_INBOX/                    # batch copies of inputs
02_WORKING_BUCKETS/
  buckets/                  # one folder per bucket (bkt_<prefix>)
  db/                       # SQLite archive + migrations
  reports/                  # ingestion + QC reports
  views/                    # optional reconstructed folder trees
03_PUBLISHED_TO_PHOTOS/      # export set imported into Apple Photos
04_APPLE_PHOTOS_EXPORTS/     # controlled exports pulled from Photos
```

## SQLite Schema (minimum viable)
- `files(sha256, path, size, ext, width, height, mtime, exif_datetime, source, original_relpath, original_filename)`
- `buckets(bucket_id, bucket_prefix, source, preferred_variant, cluster_id)`
- `bucket_files(bucket_id, file_sha256, role, is_primary, notes)`
- `links(bucket_id_a, bucket_id_b, link_type, confidence)`

## Tooling Deliverables
1. `ingest.py` – walk sources, hash, populate DB, build/update bucket folders + sidecars, report orphans/ambiguities. Supports `--source`, multiple `--root`, optional `--rules`, `--dry-run`.
2. `report.py` – health metrics, orphan list, random spot-check sample.
3. `publish.py` – export preferred variant per bucket into `03_PUBLISHED_TO_PHOTOS/` with deterministic naming + provenance sidecar.
4. `review_ui.py` – local UI/CLI to compare proxy vs AI outputs and persist `preferred_variant` decisions.
5. Future: `dedupe_visual.py` for perceptual clustering.

## Execution Flow (v1)
1. Stage a batch into `01_INBOX/<batch>/`.
2. `python ingest.py --root 01_INBOX/<batch> --source mom --dry-run` for validation, then run without dry-run.
3. `python report.py` to audit coverage + spot-check.
4. `python publish.py` to refresh `03_PUBLISHED_TO_PHOTOS/`.
5. Import published folder into a dedicated Apple Photos library manually and tag `bucket:<prefix>` keywords (ExifTool workflow TBD).
6. Iterate until the process is stable, then scale up.

## Next Steps
- Scaffold Python CLI layout (argparse + shared config, logging, dry-run plumbing).
- Define JSON sidecar structure and bucket folder template.
- Draft ExifTool automation plan for applying keywords pre-import.
- Gather sample batch (≈200 assets) to verify hashing + role assignment heuristics before scaling to 2 TB.

---

## Face Review Stack (Status: messy but intact)

### Data stores (stable)
- **SQLite** (`02_WORKING_BUCKETS/db/face_embeddings.db`): face detections, embeddings, bbox, variant role, bucket linkage.
- **CSV sidecars** (`02_WORKING_BUCKETS/config/`):
  - `face_tags.csv` — face_id → label (accepted matches).  
  - `face_votes.csv` — per-label accept/reject votes.  
  - `face_ignores.csv` — ignored faces + reasons.
- **JSON metadata**: `face_people.json` (pinned/group/ignored flags per label).

These files remain the source of truth; nothing in the new UI should overwrite them unless via the documented endpoints.

### Queue server API (when `python -m cli.faces_queue` is running)
- `GET /api/people` plus `POST /api/people/pin|group|ignore`.
- `GET /api/unlabeled?limit=N&min_confidence=X`.
- `GET /api/photo/<bucket_prefix>/faces?variant=raw_front` (all faces in a photo).
- `GET /api/face/<face_id>/context` (bucket + target index for one detection).
- Queue endpoints: `/api/queue/next`, `/api/queue/seed`, `/api/queue/batch`, `/api/queue/batch/commit`, `/api/queue/seed` POST (seed label).

### Front-end modes (`templates/faces_queue`)
- **Person Review** — classic queue (accept/reject).
- **Inbox** — Unlabeled faces grid + Photos-with-unlabeled tab.
- **Photo Tagger** — hero photo with overlays, assignment panel.

### Current known issues & fixes in flight
1. **Photo Tagger should never render raw HTML errors.**  
   - Fix: ensure every fetch uses `friendlyError` + `setEmptyState`.  
2. **Photo Tagger blank state (no “kindling”).**  
   - Fix: Photo tab now opens a picker grid by default if no face context exists.
3. **People list duplication / clutter.**  
   - Fix: `normalizePeopleRoster`, collapsible sections, hover-only actions.
4. **Bounding box drift** (pending): need ResizeObserver + object-fit-aware math.

### Debug / audit checklist
Run against the live server (`PORT` from CLI output):
```bash
curl -s http://127.0.0.1:PORT/api/people | head -n 60
curl -s "http://127.0.0.1:PORT/api/unlabeled?limit=5" | head -n 80
curl -s "http://127.0.0.1:PORT/api/photo/<bucket_prefix>/faces" | head -n 120
curl -s "http://127.0.0.1:PORT/api/face/<face_id>/context" | head -n 120
```

Bounding box sanity (in Photo Tagger console):
```js
const img = document.querySelector('.photo-stage__viewport img');
const rect = img.getBoundingClientRect();
console.log({
  natural: { w: img.naturalWidth, h: img.naturalHeight },
  displayed: rect,
  fit: getComputedStyle(img).objectFit
});
```
Use those numbers in `getPhotoImageMetrics()` to map normalized bboxes correctly.

### File references
- Front-end HTML/CSS/JS: `templates/faces_queue/index.html`, `styles.css`, `queue_app.js`
- Shared helpers (error handling, roster dedupe): `queue_app.js` near the top.
- Back-end CLI entry points: `photo_archive/cli/*.py`
