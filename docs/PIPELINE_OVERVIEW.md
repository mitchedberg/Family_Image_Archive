# Family Image Archive Pipeline Cheatsheet (2025-12-26)

This guide captures the full end-to-end flow so we can onboard a new scan batch ("source") without hunting through old chats. Treat it as the canonical reference when bringing in a new library such as *Negatives Cut* or the next flatbed dump.

---

## 1. Generate AI Upscales (outside `photo_archive`)

1. Collect the raw scans for the new batch (e.g., `/Volumes/Scans_20240802/Negatives Cut`).
2. Run the standalone Topaz/PhotoRestore repo (`photo_restore 3.zip`) to produce the PRO_4K upscales into a sibling folder (e.g., `/Volumes/Scans_20240802/Negatives_Output`).
3. Spot check a handful of frames to confirm filenames stay in the `PRO_4K_<hash>_imgYYYYMMDD_HHMMSS__N.png` pattern; this is the join key we rely on later.

> ⚠️ Do **not** rename or “organize” these folders; the bucket joiners expect the original hashes and suffixes.

---

## 2. Ingest & Bucket the Source

All commands run from `photo_archive/` unless noted.

| Step | Command | Notes |
| --- | --- | --- |
| Build DB entries for new files | `python -m cli.ingest --source <label> --staged-root /path/to/scans` | Adds rows to `files` table pointing at raw/proxy/ai files. |
| Build buckets + sidecars | `python -m cli.assign --source <label> --log-level INFO` | Uses group key logic (FastFoto ID, `img_token`, etc.). For negatives we now key by `img_token` to keep each cropped frame isolated. |
| Generate derived proxies/web images | `python -m cli.thumbs --source <label> --force --log-level INFO` | Rebuilds `derived/` for smooth UI browsing. |
| (Optional) Rebuild bucket join keys | automatically handled by `cli.assign`; rerun when changing matching rules. |

> ✅ **Negatives fix**: `assigner.py` now forces negatives to group by `img_token` (including the `__N` suffix) so each front couples with its exact AI siblings even when multiple frames share the same roll hash.

---

## 3. Bucket Review UI

Launch via `launch_bucket_review.command` → pick **Bucket Review**. Prompts:

* Source filter (Family Photos / Negatives / Dad Slides / All)
* Variant control (AI only vs. AI + Originals)
* Optional bucket limit (mirrors `--limit` + `--web-limit`).

Usage tips:

* The toolbar & shortcut reference now float so we can keep keyboard focus (per latest UI tweaks).
* Finder reveal button opens the active variant (original, AI, or back) so you can compare outside the browser.
* OCR notes auto-load into the bucket notes panel; changing the text immediately flags that bucket as “human touched.” Use the “Draft / Can’t read” status to park difficult cards.

---

## 4. OCR Pipeline

* CLI: `python -m cli.ocr --include-front --include-back` (supports `--auto-resume` with checkpoint in `02_WORKING_BUCKETS/config/ocr_progress.json`).
* Apple Vision OCR dumps `auto_ocr.front_text` / `auto_ocr.back_text` into each sidecar; the UI loads this on first paint.
* Editing notes in the UI promotes text to the `human` layer while preserving the machine output for auditing.
* Use the new “Apply OCR to Both” button (in progress) to kick off Apple OCR for the current bucket directly from the review screen.

Batch progress runs overnight using the new `overnight_pipeline.command` (details below) so you can start/stop without babysitting.

---

## 5. Face Pipeline

1. **Embeddings** – `python -m cli.faces --source <label> --force` to ensure every canonical front has modern YuNet/SFace descriptors. Negatives proxy-only buckets are still pending this pass (script includes it automatically now).
2. **Queue UI** – `launch_bucket_review.command` → **Face Queue** to triage and tag (defaults `--min-confidence 0.4 --min-similarity 0.45`).
3. **Exports** – `python -m cli.export_people ...` using `02_WORKING_BUCKETS/config/demo_people.txt` to publish AI vs. Original folders for the iPad demo. The exporter only touches `03_PUBLISHED_TO_PHOTOS/DEMO_PEOPLE` + manifest.

---

## 6. Duplicate Detection (pHash)

* Compute hashes: `python -m cli.phash_dupes --db-readonly --apply --threshold 8 --run-id <tag>`.
* Review pairs: `launch_bucket_review.command` → **Duplicate Reviewer** → choose the run-id. Image pairs load side-by-side with keyboard shortcuts (`m`=match, `r`=non-match, arrows to navigate, slider for distance once we expose it).
* Buckets flagged as confirmed matches can later drive auto-merging logic or AI sharing.

Upcoming enhancements: slider to change max Hamming distance + requeue only the “unknown” pairs (no more re-reviewing confirmed matches).

---

## 7. Overnight Maintenance Script

* File: `/Volumes/4TB_Sandisk_SSD/Family_Image_Archive/overnight_pipeline.command` (double-clickable; now Bash-based for reliability).
* Steps (sequential, logged under `02_WORKING_BUCKETS/logs/overnight_<timestamp>.log`):
  1. `cli.assign --source negatives`
  2. `cli.thumbs --source negatives --force`
  3. `cli.ocr --include-front --include-back`
  4. `cli.faces --source negatives --force`
  5. `cli.phash_dupes --db-readonly --apply --threshold 8 --run-id overnight_<timestamp>`
* Console output goes to `/tmp/overnight_runner.log`; tail either log to check progress. The script uses `~/myenv/bin/python` explicitly so it doesn’t depend on terminal state.

To run unattended: open Terminal and `nohup ./overnight_pipeline.command > /tmp/overnight_runner.log 2>&1 &` then tail the log for a few minutes. Kill with `pkill -f overnight_pipeline` if you need to pause.

---

## 8. Dashboard Shortcuts (`launch_bucket_review.command`)

Current menu options:

1. **Bucket Review** – existing prompts (scope, AI vs All, limit).
2. **Duplicate Reviewer** – lists the latest `phash_test/<run_id>` folders in reverse chronological order and launches `python -m cli.phash_viewer --run-id <choice>`.
3. **Face Queue** – launches `python -m cli.faces_queue --min-confidence 0.4 --min-similarity 0.45`.

Planned additions (call out when ready):

* People exporter (read-only DB) with file-picker for `people.txt`.
* OCR health monitor (to display current checkpoint/resume range).

---

## 9. Adding a New Library (checklist)

1. **Prep** – ensure the scan folder contains the raw fronts/backs plus AI upscales if available.
2. **Ingest** – run `cli.ingest` to populate database rows for that source label.
3. **Assign** – run `cli.assign --source <label>` to generate buckets + sidecars.
4. **Derived** – run `cli.thumbs --source <label> --force`.
5. **UI QA** – launch Bucket Review filtered to the new source with “AI + Originals” to verify proxies, AI attachments, and OCR overlays.
6. **OCR** – run `cli.ocr --source <label> --include-front --include-back`. (Use `--resume-prefix` if you only want a subset.)
7. **Faces** – `cli.faces --source <label>` followed by Face Queue review.
8. **Exports / Publishing** – `cli.export_people` or `cli.publish` depending on the downstream use-case.
9. **Duplicates** – run `cli.phash_dupes` + Duplicate Reviewer to clean up near-identical entries.

Once these steps pass, the source is ready for bucket preferences, Apple Photos publishing, and downstream ML.

---

## 10. Quick Commands Reference

```
# Launch UI dashboard
/Volumes/4TB_Sandisk_SSD/Family_Image_Archive/launch_bucket_review.command

# Overnight batch (assign -> thumbs -> ocr -> faces -> phash)
/Volumes/4TB_Sandisk_SSD/Family_Image_Archive/overnight_pipeline.command

# Manual monitoring
cd /Volumes/4TB_Sandisk_SSD/Family_Image_Archive
 tail -f 02_WORKING_BUCKETS/logs/overnight_<timestamp>.log
```

Keep this file close while we iterate; update the table whenever a new “micro-app” graduates to the launcher.
