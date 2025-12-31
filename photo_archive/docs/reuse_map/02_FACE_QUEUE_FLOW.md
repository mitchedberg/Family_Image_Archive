# Face Queue Flow

## Launch & Dataset
- Run `python -m cli.faces_queue` (see `photo_archive/cli/faces_queue.py`). Steps:
  - Connect to SQLite + embeddings via `archive_lib.faces.FaceMatcher`.
  - Load decisions from `config/face_tags.csv`, votes from `face_votes.csv`, ignored ids from `face_ignores.csv`.
  - Build `QueueState` (in-memory unlabeled list, grouping by label + bucket).
  - Emit `faces_queue_data.js` with summary counts for bootstrapping person-review mode.
  - Start HTTP server exposing `/views/faces_queue/index.html`.

## UI Modes
- **Person Review** (legacy panel reused from earlier queue): uses embedded dataset and `/api/queue/*` endpoints for next/accept/reject.
- **Photo Tagger** (new mode): entirely API-driven grid + hero viewer for photo-first tagging.

## Data files / stores
- `config/face_tags.csv`: confirmed label assignments per face.
- `config/face_votes.csv`: review votes (accept/reject) for label suggestions.
- `config/face_ignores.csv`: faces excluded from queue.
- `config/face_people.json`: pin/group metadata for People sidebar.
- `config/photo_priority.json`: triage priority per bucket.
- Derived assets under `02_WORKING_BUCKETS/buckets/bkt_<prefix>/derived/` for front/back JPGs.

## API endpoints (selected)
- `/api/people` – returns roster with pin/group flags.
- `/api/queue/next`, `/api/queue/accept`, `/api/queue/skip` – person-mode fetches/mutates CSV stores.
- `/api/photos?limit=&cursor=&priority` – paginated photo grid feed built from `QueueState.unlabeled_photo_groups()` plus priority metadata.
- `/api/photo/<bucket>/faces?variant=raw_front` – hero payload (`bucket_prefix`, `image_url`, `has_back`, `back_url`, `faces[]`).
- `/api/photo/priority` – POST to update triage.
- `/api/unlabeled` – list of face detections for legacy UI.

## UI Flow (Photo Tagger)
1. `ensurePhotoGridLoaded()` is called when switching to Photo mode. If empty, `refreshPhotoGrid(true)` resets state and GETs `/api/photos`.
2. Grid: `renderPhotoGrid()` builds cards; clicking card calls `openPhotoHero(index)`.
3. Hero load: `loadPhotoFaces(photo)` fetches `/api/photo/<bucket>/faces`. Payload includes normalized bbox (`0–1`), front/back URLs, `faces[]` with label state.
4. `renderPhotoHeroImage(url)` attaches `ResizeObserver`, respects zoom slider; overlay nodes created by `renderCandidateFacesOverlay` (shared helper) with color-coded state.
5. Selecting a face from overlay or sidebar sets `state.photo.activeFaceId`; “Assign to <label>” button posts to `/api/queue/accept`.
6. Priority buttons call `setPhotoPriority`, which writes `photo_priority.json` and re-sorts grid.
7. Back toggle uses `handlePhotoBackToggle` to load `back_url` and hide overlays while viewing handwriting.

## BBox coordinate system
- `FaceRecord.bbox` values are normalized floats `[left, top, width, height]` relative to original scan (0–1).
- Frontend converts to pixels via `getRenderedImageRect(wrapper,img)` (calculating actual drawn width/height accounting for letterboxing) before positioning overlay boxes.
- `ResizeObserver` re-runs overlay positioning when hero dimensions change or zoom slider updates CSS height.

## Sequence example
```
User clicks photo tile → openPhotoHero(index)
  → state.photo.heroMeta = selected photo; showPhotoGrid(false)
  → loadPhotoFaces(photo)
      → GET /api/photo/<bucket>/faces
      → payload includes faces[], image_url, has_back
      → renderPhotoFaceList() + renderPhotoHeroImage(front)
      → ResizeObserver installed, overlays drawn for each bbox
User clicks "Assign to Shelley" button on a face
  → POST /api/queue/accept {face_id,label}
  → FaceTagStore updates CSV, server responds {status:ok}
  → UI decrements photo.unlabeled_count, updates overlay color.
```
