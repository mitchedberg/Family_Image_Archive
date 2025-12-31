# Extraction Plan

## Phase 1 – Copy helpers without changing behavior
1. **Create shared modules**
   - `photo_archive/static/lib/api_client.js` containing current `checkResponse` + Abort helpers.
   - `photo_archive/static/lib/pref_store.js` importing the safe `localStorage` wrappers from face queue.
   - `archive_lib/bucket_assets.py` with `_find_variant_path` + `_bucket_asset_url` logic.
2. **Touch files**: copy code only; update both frontends/backends to import new helpers but keep old call sites as wrappers.
3. **Validation**: run both CLIs (`python -m cli.review`, `python -m cli.faces_queue`), confirm no functional change; verify through browser smoke test.
4. **Rollback**: restore previous JS files (we already have `templates/*_legacy_*.js`).

## Phase 2 – Adopt shared helpers in Photo Tagger (smaller blast radius)
1. Swap Photo Tagger to use `api_client.requestJSON` + `pref_store` and new `bucket_assets` resolver for `/api/photo/<bucket>/faces`.
2. Update `cli/faces_queue.py` to import resolver helper.
3. **Files**: `templates/faces_queue/queue_app.js`, `photo_archive/cli/faces_queue.py`.
4. **Validation**: regression test Photo Tagger (grid load, back toggle, priority). No changes to Bucket Review yet.
5. **Rollback**: revert queue JS + CLI file; shared modules remain unused but harmless.

## Phase 3 – Adopt shared helpers in Bucket Review
1. Replace ad-hoc fetches (`_handle_decision`, `/api/ocr`) with `api_client` wrapper.
2. Use `pref_store` for zoom + compare mode.
3. Swap `_find_variant_path` calls with shared `bucket_assets` functions (server + dataset builder) to align front/back resolution.
4. Optionally begin fetching OCR/voice from shared API instead of baked data (behind flag).
5. **Validation**: manual bucket walkthrough (front/back toggle, zoom, OCR copy, note save).
6. **Rollback**: revert `review_app.js` + `cli/review.py`; dataset generator still uses shared helper but original functions kept as wrappers until confident.

## Phase 4 – Extract higher-level UI pieces
1. Build shared `ui/image_viewer.js` + `ui/overlay_math.js` based on Phase 2 learnings.
2. Integrate into Photo Tagger first (since overlays already modular). When stable, adopt inside Bucket Review (for future face overlay features or for zoom/back toggles).
3. Introduce canonical `photo_context` endpoint on backend using shared payload schema; migrate Photo Tagger to it, then update Bucket Review to optionally fetch live data (enables incremental updates without re-running CLI).
4. **Validation**: repeated multi-browser smoke tests, measure scroll/zoom behavior, ensure overlays stay aligned after resize.
5. **Rollback**: keep legacy JS copies (already present) + use environment flag to pick old/new modules.

## Phase 5 – Clean-up & deletion
1. Remove duplicated helper code from both repos once shared modules are stable.
2. Document new APIs/modules (`docs/reuse_map` becomes living doc).
3. Keep `templates/*_legacy_YYYYMMDD` snapshots to revert quickly during future experiments.
