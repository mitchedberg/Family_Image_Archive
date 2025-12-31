# Repo Audit Packet

Generated: 2025-12-30
Captured on host: /Volumes/4TB_Sandisk_SSD/Family_Image_Archive

---

## 1) Architecture map (where code lives)

### Short repo tree (important dirs only)

```
photo_archive
├── archive_lib/            # Core libs (db, tags, votes, ignores, transforms, matcher, ocr)
├── cli/                    # Entry points for servers + pipelines
├── docs/reuse_map/         # Reuse/onboarding docs
├── templates/              # HTML/CSS/JS for local UIs
│   ├── faces_queue/        # Face Queue UI (Photo Tagger + per-person flow)
│   └── review/             # Bucket Review UI (front/back/AI compare)
└── scripts/                # DB init & reports
```

### Bucket Review UI

**Entrypoint:** `photo_archive/cli/review.py` (Typer command `python -m cli.review`)
- Builds dataset + web previews, writes view assets, starts local HTTP server.
- Copies `templates/review/*` → `02_WORKING_BUCKETS/views/review/` and serves from there.

**Templates:**
- `photo_archive/templates/review/index.html` — layout, toolbar, panels, shortcuts.
- `photo_archive/templates/review/styles.css` — UI/interaction styles.
- `photo_archive/templates/review/review_app.js` — state + all UI logic.
  - State owned in JS: `state.zoom`, `state.pan`, `state.compareMode`, selection indexes, notes panel state, filters.

**Data stores + modules:**
- SQLite: `cfg.db_path` (loaded via `archive_lib/db.py`) for bucket metadata, OCR, etc.
- Decisions: `config/ai_choices.csv` via `archive_lib/decisions.py` (DecisionStore).
- Back rotation transforms: `config/photo_transforms.json` via `archive_lib/photo_transforms.py`.
- Sidecar notes: `bkt_<bucket>/sidecar.json` (read/write in `cli/review.py`).
- Voice transcripts: `02_WORKING_BUCKETS/voice_sessions/transcripts/*` (read in `cli/review.py`).
- OCR: uses `archive_lib/ocr.py` + sidecar updates in `cli/review.py`.

### Face Queue UI (Photo Tagger + per-person queue)

**Entrypoint:** `photo_archive/cli/faces_queue.py` (Typer command `python -m cli.faces_queue`)
- Loads face embeddings + labels, writes view assets, starts local HTTP server.
- Copies `templates/faces_queue/*` → `02_WORKING_BUCKETS/views/faces_queue/` and serves from there.

**Templates:**
- `photo_archive/templates/faces_queue/index.html` — layout (person mode + photo mode + audit panel).
- `photo_archive/templates/faces_queue/styles.css` — UI/interaction styles.
- `photo_archive/templates/faces_queue/queue_app.js` — state + all UI logic.
  - State owned in JS: people roster, queue candidate, photo grid, hero, overlays, filters, zoom/pan, prompt state.

**Data stores + modules:**
- SQLite: `cfg.db_path` (face embeddings in DB) via `archive_lib/db.py`.
- Face tags: `config/face_tags.csv` via `archive_lib/face_tags.py`.
- Face votes (accept/reject history): `config/face_votes.csv` via `archive_lib/face_votes.py`.
- Face ignores: `config/face_ignores.csv` via `archive_lib/face_ignores.py`.
- People roster: `config/face_people.json` via `archive_lib/face_people.py`.
- Photo priority: `config/photo_priority.json` via `archive_lib/photo_priority.py`.
- Photo done status: `config/face_photos.json` via `PhotoStatusStore` in `cli/faces_queue.py`.
- Photo transforms: `config/photo_transforms.json` via `archive_lib/photo_transforms.py`.
- Manual face boxes: `config/manual_boxes.json` via `ManualBoxStore` in `cli/faces_queue.py`.

---

## 2) Viewer stack inventory (reuse gold)

### Bucket Review UI (zoom/pan + front/back)

**Zoom/Pan (transform-based)**
- `photo_archive/templates/review/review_app.js`:
  - `registerPointerHandlers()` wires `handlePointerDown`, `handlePointerMove`, `handlePointerUp`, `handleWheel`.
  - `nudgeZoom(delta)` updates `state.zoom`, then reapplies transforms.
  - `applyZoomTransform()` logic is applied in `render()` via:
    - `const panZoom = translate(...) scale(...)`
    - applied to `.zoom-canvas` elements with rotation appended.
  - Persisted in `localStorage` keys: `review_zoom`, `review_pan`.

**Front/Back selection + missing back handling**
- `photo_archive/templates/review/review_app.js`:
  - `setCompareMode(mode)` switches between `ai` and `back`.
  - In `renderComparePane()` (around the back pane rendering), missing back yields:
    - `<div class="pane pane--empty">No back image attached to this bucket.</div>`
  - Back rotation controls live in the same file (`data-back-rotate` handlers) and persist via `/api/photo/transform`.

**Keyboard navigation**
- `photo_archive/templates/review/review_app.js`:
  - Global key handler (near top): J/K navigate, 1/2/3 apply decisions, +/- zoom, 0 reset, V verify+next, etc.

### Face Queue UI (photo tagger viewer)

**Zoom/Pan (shared transform unit)**
- `photo_archive/templates/faces_queue/queue_app.js`:
  - `applyPhotoZoom()` applies `translate + scale` to `#photo-zoom-canvas` (image + overlay together).
  - `handlePhotoWheelZoom`, `handlePhotoPanStart/Move/End` control zoom/pan.

**Front/Back swap + missing back behavior**
- `photo_archive/templates/faces_queue/queue_app.js`:
  - `handlePhotoBackToggle()` toggles `state.photo.viewingBack` and calls `renderPhotoHeroImage()`.
  - Missing back/front shows status + keeps UI navigable.

**Keyboard nav**
- `photo_archive/templates/faces_queue/queue_app.js`:
  - `handlePhotoModeHotkeys()` for ←/→, tab face cycling, D done, P priority, B front/back, G grid.
  - Global `handleHotkeys()` for single queue (T accept, F reject, etc.).

**Object-fit/contain metrics (bbox alignment)**
- `photo_archive/templates/faces_queue/queue_app.js`:
  - `getRenderedImageRect(wrapper, img)` computes drawWidth/drawHeight + offsets.
  - `positionBoundingBox()` uses those metrics to align face boxes.

---

## 3) Face workflow truth table (persisted vs not)

**Accept / Reject / Ignore persistence**
- Accept / tag:
  - `photo_archive/cli/faces_queue.py::_handle_accept()` → `archive_lib/face_tags.py` writes `config/face_tags.csv`.
- Reject (vote against label):
  - `photo_archive/cli/faces_queue.py::_handle_reject()` → `archive_lib/face_votes.py` writes `config/face_votes.csv`.
- Ignore (never show again):
  - `photo_archive/cli/faces_queue.py::_handle_ignore()` → `archive_lib/face_ignores.py` writes `config/face_ignores.csv`.

**Are rejected pairings consulted?**
- Yes. `cli/faces_queue.py::_serve_next_candidate()` and `_handle_batch_request()` pass `vote_store.rejected_for(label)` into `FaceMatcher.next_candidate()` / `ranked_candidates()`.

**How “unlabeled” is defined today**
- Per-face: `QueueState.unlabeled_ids` is built from face embeddings where `face_id` not in tags and not ignored.
- Per-photo: `QueueState.unlabeled_photo_groups(min_confidence)` aggregates the per-face list by `bucket_prefix`.

**What prevents garbage detections from lingering forever**
- Detector confidence filter (server): `min_confidence` in `QueueState`.
- Client filters (Face Queue UI): min confidence slider, min face area, hide labeled.
- Done buckets: `config/face_photos.json` done state is now excluded from:
  - `/api/unlabeled`, `/api/queue/next`, `/api/queue/batch`, `/api/photos` (default), `/api/label/photos` (default).

---

## 4) API contract snapshots (real JSON)

Captured from a running Face Queue server at `http://127.0.0.1:50510` (started via `BROWSER=true python -m cli.faces_queue`).

### `/api/people` (first ~2 items)
```json
{
  "status": "ok",
  "people": [
    {
      "label": "Adam Bell",
      "face_count": 2,
      "pending_count": 0,
      "last_seen": "2025-12-24T17:59:29.523668+00:00",
      "pinned": false,
      "group": "",
      "ignored": false
    },
    {
      "label": "Adam Peck",
      "face_count": 5,
      "pending_count": 1,
      "last_seen": "2025-12-24T18:52:59.690869+00:00",
      "pinned": false,
      "group": "",
      "ignored": false
    }
  ]
}
```

### `/api/photos?limit=3`
```json
{
  "status": "ok",
  "photos": [
    {
      "bucket_prefix": "d459f8bfe850",
      "bucket_source": "family_photos",
      "image_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
      "unlabeled_count": 10,
      "max_confidence": 0.9492204189300537,
      "done": false,
      "priority": "normal",
      "labeled_count": 0,
      "has_front": true,
      "front_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
      "has_back": false
    },
    {
      "bucket_prefix": "badbac4d70c9",
      "bucket_source": "uncle",
      "image_url": "/buckets/bkt_badbac4d70c9/derived/web_front.jpg",
      "unlabeled_count": 10,
      "max_confidence": 0.9478647708892822,
      "done": false,
      "priority": "normal",
      "labeled_count": 0,
      "has_front": true,
      "front_url": "/buckets/bkt_badbac4d70c9/derived/web_front.jpg",
      "has_back": true,
      "back_url": "/buckets/bkt_badbac4d70c9/derived/web_back.jpg"
    }
  ],
  "total_photos": 6651,
  "remaining_estimate": 20038,
  "cursor": 0,
  "next_cursor": 3,
  "has_more": true,
  "priority_filter": "all"
}
```

### `/api/photos?mode=review&limit=3`
```json
{
  "status": "ok",
  "photos": [
    {
      "bucket_prefix": "24a4824c7442",
      "bucket_source": "family_photos",
      "image_url": "/buckets/bkt_24a4824c7442/derived/web_front.jpg",
      "unlabeled_count": 9,
      "max_confidence": 0.9449002146720886,
      "labeled_count": 1,
      "done": false,
      "priority": "normal",
      "has_front": true,
      "front_url": "/buckets/bkt_24a4824c7442/derived/web_front.jpg",
      "has_back": false
    }
  ],
  "total_photos": 3902,
  "remaining_estimate": 20038,
  "cursor": 0,
  "next_cursor": 3,
  "has_more": true,
  "priority_filter": "all"
}
```

### `/api/photo/d459f8bfe850/faces`
```json
{
  "status": "ok",
  "bucket_prefix": "d459f8bfe850",
  "variant": "raw_front",
  "image_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
  "front_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
  "has_front": true,
  "has_back": false,
  "back_url": null,
  "faces": [
    {
      "face_id": "d459f8bfe850:0",
      "variant": "raw_front",
      "confidence": 0.9492204189300537,
      "bbox": {"left": 0.5270259346, "top": 0.2725508214, "width": 0.0411401816, "height": 0.0817106602},
      "state": {"label": null, "vote": null, "ignored": false, "ignore_reason": null}
    }
  ]
}
```

### `/api/label/photos?label=Adam%20Bell&limit=3`
```json
{
  "status": "ok",
  "label": "Adam Bell",
  "photos": [
    {
      "bucket_prefix": "d879aa5361c8",
      "bucket_source": "family_photos",
      "image_url": "/buckets/bkt_d879aa5361c8/derived/web_front.jpg",
      "unlabeled_count": 1,
      "max_confidence": 0.934866726398468,
      "labeled_count": 9,
      "done": false,
      "priority": "normal",
      "has_front": true,
      "front_url": "/buckets/bkt_d879aa5361c8/derived/web_front.jpg",
      "has_back": false
    }
  ],
  "total_photos": 2,
  "offset": 0,
  "limit": 3,
  "has_more": false,
  "next_offset": null
}
```

---

## 5) Known issues (short list with repro)

1) **Summary “unlabeled remaining” still includes done buckets**
- Steps: mark a bucket done; look at summary in top bar.
- Expected: remaining count drops immediately.
- Actual: count unchanged (done buckets still included in `QueueState.unlabeled_remaining`).
- Suspected file: `photo_archive/cli/faces_queue.py` (`QueueState.unlabeled_remaining`).

2) **Manual boxes don’t participate in similarity matching**
- Steps: draw a manual box, label it, then wait for similar candidates.
- Expected: manual face embeddings should generate candidates.
- Actual: manual boxes have no embeddings, so they never seed candidate matches.
- Suspected file: `photo_archive/cli/faces_queue.py` (`_handle_manual_box` + embedding generation not present).

3) **Some buckets lack web_front/back and still appear in grids**
- Steps: open a bucket with missing web_front or web_back.
- Expected: hidden or “missing asset” flag; should not hang.
- Actual: still appears; now shows “Missing front” badge + error banner, but still clutters queues.
- Suspected file: `photo_archive/cli/faces_queue.py` (`_serve_unlabeled_photos` / `_serve_label_photos`).

4) **Done buckets not removed from QueueState cache**
- Steps: mark done, keep single queue running for long session.
- Expected: done buckets should never reappear even as matcher state shifts.
- Actual: endpoints filter done buckets, but `QueueState` still holds IDs (only filtered at endpoint).
- Suspected file: `photo_archive/cli/faces_queue.py` (`QueueState` + endpoint filters only).

5) **No per-bucket min-confidence override**
- Steps: run into a bucket with many hand/false detections; want to hide them permanently.
- Expected: store per-bucket min_conf override and filter on `/api/photo/<bucket>/faces` + `/api/unlabeled`.
- Actual: only global min_confidence is supported.
- Suspected file: `photo_archive/cli/faces_queue.py` (`_serve_photo_faces`, `_serve_unlabeled`).

6) **Candidate prompt lacks “don’t ask again this session”**
- Steps: accept many faces; prompt appears each time.
- Expected: toggle to suppress prompt per session.
- Actual: prompt appears every accept (though auto-defaults after 1.5s).
- Suspected file: `photo_archive/templates/faces_queue/queue_app.js` (candidate prompt logic).

---

### Notes
- Face Queue assets are copied into `02_WORKING_BUCKETS/views/faces_queue/` on server start; if UI doesn’t reflect changes, hard-refresh or restart `python -m cli.faces_queue`.
- Bucket Review assets are copied into `02_WORKING_BUCKETS/views/review/` on server start; same cache guidance.

---

## Appendix: Handoff Checklist (what a new agent needs)

### Current working assumptions
- Face Queue UI is the primary surface for photo-first tagging; Bucket Review remains the better zoom/back/notes UI.
- Done buckets must be excluded from all feeds by default (unlabeled, queue, batch, photo grids).
- Manual boxes stay JSON-backed for now (no SQLite migration mid-shipping).
- Any missing-front/failed-image case must fail gracefully with skip/mark-done actions (no nav dead-ends).

### Last known server behavior (for quick verification)
- Start: `python -m cli.faces_queue`
- Sample endpoints:
  - `/api/people`
  - `/api/photos?limit=3`
  - `/api/photos?mode=review&limit=3`
  - `/api/photo/<bucket>/faces`
  - `/api/label/photos?label=<LABEL>&limit=3`

### First tests if something looks off
1) Hard refresh with cache disabled; restart server to recopy templates.
2) Confirm `/api/label/photos` returns data for a known label.
3) Mark a bucket done → ensure it disappears from `/api/unlabeled`, `/api/queue/next`, `/api/queue/batch`.
4) Open hero on a missing image → ensure timeout banner appears and navigation still works.
5) Click a different face box in single view → accept should tag the clicked face (not the original).
