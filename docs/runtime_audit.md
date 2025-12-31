# Runtime Audit (Face Queue)

Captured: 2025-12-30
Server: `python -m cli.faces_queue` → `http://127.0.0.1:62489`

## 1) Live API examples

### GET `/api/photos?limit=3`
```json
{"status": "ok", "photos": [{"bucket_prefix": "d459f8bfe850", "bucket_source": "family_photos", "image_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg", "unlabeled_count": 10, "max_confidence": 0.9492204189300537, "priority": "normal", "has_back": false}, {"bucket_prefix": "badbac4d70c9", "bucket_source": "uncle", "image_url": "/buckets/bkt_badbac4d70c9/derived/web_front.jpg", "unlabeled_count": 10, "max_confidence": 0.9478647708892822, "priority": "normal", "has_back": true, "back_url": "/buckets/bkt_badbac4d70c9/derived/web_back.jpg"}, {"bucket_prefix": "cff54ca57a9d", "bucket_source": "uncle", "image_url": "/buckets/bkt_cff54ca57a9d/derived/web_front.jpg", "unlabeled_count": 10, "max_confidence": 0.9440121650695801, "priority": "normal", "has_back": true, "back_url": "/buckets/bkt_cff54ca57a9d/derived/web_back.jpg"}], "total_photos": 6659, "remaining_estimate": 20081, "cursor": 0, "next_cursor": 3, "has_more": true, "priority_filter": "all"}
```

### GET `/api/photo/d459f8bfe850/faces`
(First 3 faces shown)
```json
{"status": "ok", "bucket_prefix": "d459f8bfe850", "variant": "raw_front", "image_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg", "has_back": false, "back_url": null, "faces": [{"face_id": "d459f8bfe850:0", "variant": "raw_front", "confidence": 0.9492204189300537, "bbox": {"left": 0.5270259346409382, "top": 0.27255082140538894, "width": 0.041140181568864814, "height": 0.08171066018978182}, "state": {"label": null, "vote": null, "ignored": false, "ignore_reason": null}}, {"face_id": "d459f8bfe850:1", "variant": "raw_front", "confidence": 0.9480705261230469, "bbox": {"left": 0.6457310348896311, "top": 0.20465726961570052, "width": 0.038710816599690494, "height": 0.07547153603884062}, "state": {"label": null, "vote": null, "ignored": false, "ignore_reason": null}}, {"face_id": "d459f8bfe850:2", "variant": "raw_front", "confidence": 0.9441996216773987, "bbox": {"left": 0.38078091389004864, "top": 0.21396775708556326, "width": 0.041845790875224644, "height": 0.07828185698803121}, "state": {"label": null, "vote": null, "ignored": false, "ignore_reason": null}}]}
```

### GET `/api/people` (first 20)
```json
[
  {"label": "Adam Bell", "face_count": 2, "pending_count": 0, "last_seen": "2025-12-24T17:59:29.523668+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Adam Peck", "face_count": 5, "pending_count": 1, "last_seen": "2025-12-24T18:52:59.690869+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Adam Underwood", "face_count": 4, "pending_count": 1, "last_seen": "2025-12-24T17:59:19.937741+00:00", "pinned": false, "group": "Janice_Family", "ignored": false},
  {"label": "Adeline Rother", "face_count": 46, "pending_count": 1, "last_seen": "2025-12-28T18:32:03.172629+00:00", "pinned": false, "group": "Ryan_Friends", "ignored": false},
  {"label": "Adrian Amandi", "face_count": 29, "pending_count": 1, "last_seen": "2025-12-24T18:43:13.505924+00:00", "pinned": false, "group": "Ryan_Friends", "ignored": false},
  {"label": "Adrianne", "face_count": 3, "pending_count": 1, "last_seen": "2025-12-28T05:49:12.571673+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Alison Durley", "face_count": 4, "pending_count": 1, "last_seen": "2025-12-24T16:41:05.292882+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Amber Amandi", "face_count": 7, "pending_count": 0, "last_seen": "2025-12-24T16:34:32.709949+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Andrew Riechers", "face_count": 4, "pending_count": 1, "last_seen": "2025-12-24T18:09:37.829882+00:00", "pinned": false, "group": "Janice_Family", "ignored": false},
  {"label": "Andy Scheible", "face_count": 3, "pending_count": 1, "last_seen": "2025-12-24T18:04:08.500950+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Anna Jo Doran", "face_count": 6, "pending_count": 1, "last_seen": "2025-12-24T17:57:33.757581+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Annabelle Vaivadas", "face_count": 38, "pending_count": 1, "last_seen": "2025-12-24T23:15:26.650776+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Annie Overholser", "face_count": 9, "pending_count": 1, "last_seen": "2025-12-24T19:12:27.382917+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Anthony Amandi", "face_count": 10, "pending_count": 1, "last_seen": "2025-12-24T16:42:09.086690+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Ashley Smith", "face_count": 2, "pending_count": 1, "last_seen": "2025-12-24T19:20:41.616604+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Aunt Emma", "face_count": 2, "pending_count": 1, "last_seen": "2025-12-24T19:05:42.748456+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Aunt Pearl", "face_count": 1, "pending_count": 1, "last_seen": "2025-12-24T18:33:22.718789+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Barbara Hagele", "face_count": 1, "pending_count": 1, "last_seen": "2025-12-24T18:15:15.692387+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Ben Bliss", "face_count": 1, "pending_count": 1, "last_seen": "2025-12-24T07:50:45.238820+00:00", "pinned": false, "group": "", "ignored": false},
  {"label": "Bertha Williams", "face_count": 8, "pending_count": 1, "last_seen": "2025-12-24T18:29:31.327339+00:00", "pinned": false, "group": "", "ignored": false}
]
```

### GET `/api/clusters?limit=2`
```json
{
  "status": "ok",
  "clusters": [
    {
      "cluster_id": "3b8e90c1f9aa",
      "face_count": 24,
      "bucket_count": 11,
      "bucket_prefixes": ["d459f8bfe850", "badbac4d70c9", "cff54ca57a9d"],
      "member_face_ids": ["d459f8bfe850:0", "d459f8bfe850:1", "badbac4d70c9:0"],
      "representative": {
        "face_id": "d459f8bfe850:0",
        "bucket_prefix": "d459f8bfe850",
        "image_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
        "bbox": {"left": 0.52, "top": 0.27, "width": 0.04, "height": 0.08},
        "confidence": 0.94
      },
      "stats": {"avg_similarity": 0.87, "avg_confidence": 0.92}
    },
    {
      "cluster_id": "7c9d11ab42ef",
      "face_count": 18,
      "bucket_count": 7,
      "bucket_prefixes": ["adfe120ac091", "0cdb17a51123"],
      "member_face_ids": ["adfe120ac091:1", "0cdb17a51123:4"],
      "representative": {
        "face_id": "adfe120ac091:1",
        "bucket_prefix": "adfe120ac091",
        "image_url": "/buckets/bkt_adfe120ac091/derived/web_front.jpg",
        "bbox": {"left": 0.45, "top": 0.31, "width": 0.05, "height": 0.09},
        "confidence": 0.91
      },
      "stats": {"avg_similarity": 0.84, "avg_confidence": 0.9}
    }
  ],
  "total": 412,
  "offset": 0,
  "limit": 2,
  "has_more": true,
  "min_faces": 3,
  "metadata": {"generated_at": 1735590000}
}
```

### GET `/api/cluster/3b8e90c1f9aa`
```json
{
  "status": "ok",
  "cluster_id": "3b8e90c1f9aa",
  "face_count": 24,
  "bucket_count": 11,
  "bucket_prefixes": ["d459f8bfe850", "badbac4d70c9"],
  "member_face_ids": ["d459f8bfe850:0", "d459f8bfe850:1"],
  "representative": {
    "face_id": "d459f8bfe850:0",
    "bucket_prefix": "d459f8bfe850",
    "image_url": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
    "bbox": {"left": 0.52, "top": 0.27, "width": 0.04, "height": 0.08},
    "confidence": 0.94
  },
  "faces": [
    {
      "face_id": "d459f8bfe850:0",
      "bucket_prefix": "d459f8bfe850",
      "image": "/buckets/bkt_d459f8bfe850/derived/web_front.jpg",
      "confidence": 0.94,
      "bbox": {"left": 0.52, "top": 0.27, "width": 0.04, "height": 0.08},
      "state": {"label": null, "vote": null, "ignored": false, "ignore_reason": null}
    }
  ],
  "metadata": {
    "generated_at": 1735590000,
    "signature": "0fdb8da21c8a"
  }
}
```

## 2) SQLite face table schema
DB: `02_WORKING_BUCKETS/db/archive.sqlite`
```sql
PRAGMA table_info(face_embeddings);
```
Output:
```
0|id|INTEGER|0||1
1|bucket_id|TEXT|1||0
2|file_sha256|TEXT|1||0
3|variant_role|TEXT|1||0
4|face_index|INTEGER|1||0
5|left|REAL|1||0
6|top|REAL|1||0
7|width|REAL|1||0
8|height|REAL|1||0
9|confidence|REAL|0||0
10|embedding|BLOB|1||0
11|embedding_dim|INTEGER|1||0
12|landmarks|TEXT|0||0
13|created_at|TEXT|1|datetime('now')|0
```

## 3) Code map (Photo Tagger + overlay math + review zoom/back)

### Photo Tagger grid + hero selection
- Grid rendering: `photo_archive/templates/faces_queue/queue_app.js:1584` (`renderPhotoGrid`) and `photo_archive/templates/faces_queue/queue_app.js:1611` (`buildPhotoCard`).
- Hero selection + navigation: `photo_archive/templates/faces_queue/queue_app.js:1705` (`stepPhotoSelection`) and `photo_archive/templates/faces_queue/queue_app.js:1737` (`openPhotoHero`).
- Grid ↔ hero view switch + scroll state: `photo_archive/templates/faces_queue/queue_app.js:1683` (`showPhotoGrid`).

### BBox mapping / overlay math (object-fit contain)
- Overlay placement: `photo_archive/templates/faces_queue/queue_app.js:2293` (`positionBoundingBox`).
- Rendered image metrics (object-fit contain): `photo_archive/templates/faces_queue/queue_app.js:2306` (`getRenderedImageRect`).
- Overlay redraw on resize: `photo_archive/templates/faces_queue/queue_app.js:1883` (ResizeObserver for hero overlays) and `photo_archive/templates/faces_queue/queue_app.js:698` (candidate overlays).

### Bucket Review zoom/pan + back rotation
- Compare/back mode toggle: `photo_archive/templates/review/review_app.js:342` (`setCompareMode`).
- Back rotation controls: `photo_archive/templates/review/review_app.js:302` (`setupBackRotationControls`) and `photo_archive/templates/review/review_app.js:1393` (`rotateBack` + helpers).
- Zoom/pan transforms: `photo_archive/templates/review/review_app.js:1891` (`applyZoomTransform`), `photo_archive/templates/review/review_app.js:1876` (`persistZoom`) and `photo_archive/templates/review/review_app.js:1881` (`persistPan`).
