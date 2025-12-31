# Shared Component Candidates

## Component: overlay_math.js
- **What it does**: normalize bbox coordinates, compute rendered image rect, draw face boxes, hide overlays when handwriting view is active.
- **Currently in**:
  - Bucket Review: not yet (only zoom/pan on `.zoom-canvas` via `applyZoomTransform`, `getRotationFitScale`).
  - Face Queue: `renderPhotoOverlay`, `getRenderedImageRect`, `renderCandidateFacesOverlay` inside `templates/faces_queue/queue_app.js`.
- **Inputs / Outputs** (proposal):
  - `computeRenderRect(wrapperEl, imgEl) -> {drawWidth, drawHeight, offsetX, offsetY}`
  - `renderFaceBoxes(layerEl, faces, metrics, {activeId, palette})`
  - `toggleOverlay(layerEl, visible)`
- **Gotchas**: bucket review rotates back images (needs rotation-aware metrics); both run inside ResizeObserver.
- **Quick win score**: 4 (copy face-queue helper into shared file, import in bucket review when overlays land).

## Component: image_viewer.js
- **What it does**: unify grid/hero flow (show grid, open hero, next/prev, scroll preservation), zoom slider binding, back toggle hook.
- **Currently in**:
  - Bucket Review: `nextBucket`, `prevBucket`, zoom controller functions, compare toggle, `prefetchImages`.
  - Face Queue: `ensurePhotoGridLoaded`, `showPhotoGrid`, `openPhotoHero`, `stepPhotoSelection`, `applyPhotoZoom`, `handlePhotoBackToggle`.
- **Inputs / Outputs**:
  - Accepts `items[]`, `loadItem(index)` and `fetchMore()` callbacks, plus DOM references.
  - Emits events (`onSelectionChange`, `onZoomChange`).
- **Gotchas**: bucket review dataset is static (no pagination) whereas Photo Tagger scrolls + pages; module needs optional pagination support.
- **Quick win score**: 3 (requires adapter layer but removes duplicated code).

## Component: api_client.js
- **What it does**: standardize fetch + JSON parsing + error handling.
- **Currently in**:
  - Bucket Review: ad-hoc `fetch('/api/decision')` calls; HTML errors bubble to status bar.
  - Face Queue: local `checkResponse()` (already improved) reused across endpoints.
- **Inputs / Outputs**:
  - `requestJSON(url, opts) -> Promise<object>` with automatic error extraction from JSON or text.
  - optional streaming helper for `/api/fullres`.
- **Gotchas**: bucket review fetches binary (`/api/fullres`) and interacts with OS reveal endpoints (non-JSON). Provide method selection.
- **Quick win score**: 5 (copy existing helper into `static/lib/api_client.js`).

## Component: pref_store.js
- **What it does**: guard `localStorage` access, provide typed getters/setters for zoom/overlay/compare settings.
- **Currently in**:
  - Review: uses `localStorage.setItem('review_zoom', …)` directly; no try/catch.
  - Face Queue: `getStoredPreference`/`setStoredPreference` wrappers near bottom of `queue_app.js`.
- **Inputs / Outputs**:
  - `pref.get(key, fallback)` returns parsed number/bool/string.
  - `pref.set(key, value)` stringifies.
- **Gotchas**: Safari private mode, server-rendered `review_data.js` must not crash when storage unavailable.
- **Quick win score**: 4.
