# Implementation Plan (v1)

## Common Foundations
- **Language:** Python 3.11 (system install). Use only stdlib + Pillow + sqlite3 + rich (optional) to avoid heavy deps.
- **Shared Module:** Create `archive_lib/` package containing:
  - `config.py` – resolves project root, staging paths, logging setup, dry-run helper.
  - `db.py` – functions to open SQLite connection, run migrations, and helper CRUD wrappers.
  - `hashing.py` – chunked SHA256 helper with optional caching table.
  - `media.py` – Pillow-based dimension + EXIF extraction with graceful fallback for TIFF/JPEG.
  - `rules.py` – parse optional YAML/JSON overrides for front/back heuristics.
  - `buckets.py` – logic for bucket id resolution, folder creation, sidecar serialization.
- **Logging:** standard logging + progress output; all CLIs accept `--dry-run`, `--log-level`.

## ingest.py
1. **Inputs:** `--root PATH` (repeatable), `--source mom|dad|uncle|other`, `--rules rules.yaml`, `--dry-run`, `--force-rehash`.
2. **Process:**
   - Walk each root, build `original_relpath` relative to the provided root.
   - Skip non-image files unless explicitly allowed later.
   - Compute SHA256 (cache hits avoid recompute unless `--force-rehash`).
   - Collect metadata (size, ext, mtime, width, height, EXIF datetime).
   - Insert/update `files` row (UPSERT on sha256).
   - Determine file role via heuristics + rules (suffix `_front`, `_back`, `_AI`, etc.).
   - Resolve/ensure bucket:
     - Use `raw_front` TIFF if available for bucket hash; else fallback.
     - Bucket folder path: `02_WORKING_BUCKETS/buckets/bkt_<bucketprefix>/`.
     - Write `sidecar.json` (bucket metadata, provenance, variant listing).
   - Link file via `bucket_files` row.
   - Generate ingestion report (`reports/ingest_<timestamp>.json`) with:
     - New buckets created, skipped duplicates, orphans, ambiguous pairings.
3. **Idempotence:** skip if file already attached to bucket unless metadata changed; use transactions + WAL.

## report.py
- Read DB and emit textual + JSON summary to `reports/report_<timestamp>.json`.
- Metrics: bucket counts by role coverage, total files per source, list of orphan files, random sample of bucket IDs for manual QA.
- CLI flags: `--json`, `--sample-size 10`, `--role front|back`.

## publish.py
1. Determine `preferred_variant` per bucket (default `ai_front_v1` if present, else `proxy_front`).
2. Export/copy file into `03_PUBLISHED_TO_PHOTOS/<Source>/bkt_<prefix>__preferred.jpg`.
3. Generate sidecar mapping `published_map.csv` (bucket_id, bucket_prefix, preferred_variant, source, original_relpath).
4. Optionally call ExifTool (if installed) to embed keywords `bucket:<prefix>` and `source:<src>`.
5. Provide `--clean` flag to purge stale exports (prompt user + respect dry-run).

## review_ui.py
- MVP: textual TUI (Python `textual` or `rich` prompt) listing bucket, show file paths, open preview via `qlmanage` or `open` (macOS) when requested.
- For v1, implement CLI loop: print file paths, ask user to choose `ai` or `proxy`, update `buckets.preferred_variant` + sidecar.
- Later upgrade to Flask-serving simple HTML gallery.

## Future Modules
- `dedupe_visual.py`: compute phash/perceptual embeddings, cluster, update `cluster_id` + `links`.
- Apple Photos keyword automation: script stub calling `exiftool` to embed keywords prior to Photos import; optionally AppleScript for post-import tagging.

## Immediate Next Actions
1. Initialize Python package structure (`archive_lib/`, CLI entry scripts, requirements.txt, pyproject optional).
2. Draft schema migration script to create the SQLite tables inside `02_WORKING_BUCKETS/db/archive.sqlite`.
3. Implement shared config + logging skeleton, wire it into placeholder CLIs (accept args, print TODO) so flow can be exercised soon.
