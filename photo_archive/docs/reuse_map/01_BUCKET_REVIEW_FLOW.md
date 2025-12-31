# Bucket Review Flow

## Launch & Assets
- Run `python -m cli.review` (see `photo_archive/cli/review.py`). It:
  - Loads SQLite via `archive_lib.reporting.load_bucket_infos`.
  - Ensures derived JPGs (front/AI/back) exist with `archive_lib.webimage.ensure_web_images`.
  - Builds `review_data.js` + helper assets in `02_WORKING_BUCKETS/views/review/` via `_write_review_assets`.
  - Starts `ThreadingHTTPServer` serving `/views/review/index.html`.

## Templates & JS entry points
- HTML: `templates/review/index.html` renders toolbar, zoom controls, compare toggle, note drawer.
- CSS: `templates/review/styles.css` handles zoom-wrapper, drawer, filter chips.
- JS controller: `templates/review/review_app.js` manages state (`state.visible`, `state.compareMode`, zoom/pan, notes) and binds keyboard shortcuts.

## Data inputs / writes
- Static dataset `review_data.js` (baked from `_build_dataset`) contains per-bucket fields: `web_front`, `web_ai`, `web_back`, `auto_ocr`, linked voice transcripts, decision metadata, `finder_paths` for Finder reveal.
- Writes:
  - `config/ai_choices.csv` via `DecisionStore` inside `_handle_decision` (POST `/api/decision`).
  - Sidecar JSON updates for review notes + OCR status `_update_sidecar_metadata`.
  - Voice-note snapshot in `~/PhotoVoiceNotes/current_state.json` via `/api/state_update`.

## HTTP endpoints
- `/api/decision` – persist prefer AI/original flag + manual note/OCR status.
- `/api/reveal` – call OS `open -R` on Finder path.
- `/api/ocr` – run Apple Vision on `raw_back`/`proxy_back` and return text.
- `/api/state_update` – log current bucket + session to `VOICE_STATE_DIR`.
- `/api/fullres` – stream high-resolution original or AI variant for viewer (uses `_find_variant_path`).

## Front/back handling
- UI compare toggle buttons drive `setCompareMode`; state stored in localStorage.
- Rendering pipeline (`render()` → `renderComparePane`) looks at `bucket.has_back` and `state.compareMode` to determine whether to load `bucket.web_back` or fallback message.
- Back rotations persisted per bucket via `state.backRotations` + `[data-back-rotate]` buttons in `renderComparePane`.

## Navigation & Rendering
- `state.visible` holds filtered buckets. `nextBucket`/`prevBucket` update `state.index` and call `render()`.
- `render()` builds active bucket row with original + compare panes inside `.zoom-wrapper` containers.
- Zoom controls update `state.zoom`/`state.pan` and call `applyZoomTransform` to set CSS transforms on `.zoom-canvas` images.
- Prefetch: `prefetchImages(state.index)` warms future buckets.

## Notes & OCR pipeline
- Drawer toggled via `setupNotesDrawer` and `notes-toggle` button.
- `setupNoteEditor` locks manual textarea until unlocked, routes voice/OCR copy-through buttons.
- `markOcrStatus('verified')` updates UI, calls `_handle_decision` (with `ocr_status`) and optionally advances to next bucket.
- Voice/OCR tabs show `bucket.voice_transcripts` and `bucket.auto_ocr` sections.

## Sequence (example)
```
User presses "Show Back" → Button `data-compare="back"`
  → JS `setCompareMode('back')` updates state + localStorage
  → `render()` re-renders bucket: `renderComparePane` sees `state.compareMode === 'back'`
      → picks `bucket.web_back` URL (or linked-back assets) and rotates image if needed
      → zoom wrappers reuse global zoom/pan state
```

```
User edits manual note → `note-edit-toggle` unlocks textarea
  → `note-input` change triggers `debouncedNoteSave`
  → POST `/api/decision` with `bucket_prefix`, `choice`, `note`, `ocr_status`
  → server updates `DecisionStore` + bucket sidecar, returns `{status:"ok"}`
  → UI `setStatus` + note drawer summary update
```
