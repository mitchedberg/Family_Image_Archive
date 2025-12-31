# AGENTS.md

This repo hosts a preservation-focused photo archive pipeline plus two local web UIs.
Use this file as the running rules of engagement for any Codex/LLM agent.

## Source of truth
- Read `README.md` first for hard constraints about originals, bucket identity, and data stores.
- Follow the rules below when working on the Face Queue / Bucket Review UI code.

## Skills (Codex runtime)
These are discovered at startup from local sources. Each entry includes a name,
description, and file path so you can open the source for full instructions.
- skill-creator: Guide for creating effective skills. Use when users want to create
  or update a skill that extends Codex with specialized knowledge, workflows, or
  tool integrations. (file: /Users/ryanpointer/.codex/skills/.system/skill-creator/SKILL.md)
- skill-installer: Install Codex skills into $CODEX_HOME/skills from a curated list
  or a GitHub repo path. Use when a user asks to list installable skills, install a
  curated skill, or install a skill from another repo (including private repos).
  (file: /Users/ryanpointer/.codex/skills/.system/skill-installer/SKILL.md)
- Discovery: Available skills are listed in project docs and may also appear in a
  runtime "## Skills" section (name + description + file path). These are the
  sources of truth; skill bodies live on disk at the listed paths.
- Trigger rules: If the user names a skill (with `$SkillName` or plain text) OR the
  task clearly matches a skill's description, you must use that skill for that turn.
  Multiple mentions mean use them all. Do not carry skills across turns unless
  re-mentioned.
- Missing/blocked: If a named skill isn't in the list or the path can't be read,
  say so briefly and continue with the best fallback.
- How to use a skill (progressive disclosure):
  1) After deciding to use a skill, open its `SKILL.md`. Read only enough to follow
     the workflow.
  2) If `SKILL.md` points to extra folders such as `references/`, load only the
     specific files needed for the request; don't bulk-load everything.
  3) If `scripts/` exist, prefer running or patching them instead of retyping large
     code blocks.
  4) If `assets/` or templates exist, reuse them instead of recreating from scratch.
- Description as trigger: The YAML `description` in `SKILL.md` is the primary trigger
  signal; rely on it to decide applicability. If unsure, ask a brief clarification
  before proceeding.
- Coordination and sequencing:
  - If multiple skills apply, choose the minimal set that covers the request and
    state the order you'll use them.
  - Announce which skill(s) you're using and why (one short line). If you skip an
    obvious skill, say why.
- Context hygiene:
  - Keep context small: summarize long sections instead of pasting them; only load
    extra files when needed.
  - Avoid deeply nested references; prefer one-hop files explicitly linked from
    `SKILL.md`.
  - When variants exist (frameworks, providers, domains), pick only the relevant
    reference file(s) and note that choice.
- Safety and fallback: If a skill can't be applied cleanly (missing files, unclear
  instructions), state the issue, pick the next-best approach, and continue.

## Repo constraints (from README.md)
- Never modify originals (TIFF fronts/backs). Inputs are read-only.
- All scripts must be idempotent and safe to re-run.
- Bucket identity: `bucket_id = sha256(raw_front TIFF)` when available.
- File roles per bucket: `raw_front`, `proxy_front`, `ai_front_v1`, `raw_back`, `proxy_back`.
- Provenance via `source` (mom|dad|uncle|other).
- Preserve folder semantics via `original_relpath` + `original_filename`.
- Apple Photos is a published view; export preferred fronts only.

## UIs in scope
- Bucket Review UI: `python -m cli.review` → `templates/review/*`
- Face Queue UI: `python -m cli.faces_queue` → `templates/faces_queue/*`

Goal: make Face Queue Photo Tagger practical for photo-first tagging of ~10k images
with minimal risk. Do small PRs with rollback snapshots; no big refactors.

## Safety harness (non-negotiable)
1) One PR = one behavior change.
2) Before each PR, create a legacy snapshot folder:
   - `templates/faces_queue_legacy_YYYYMMDD/` (copy current `index.html`,
     `queue_app.js`, `styles.css`)
   - If touching Bucket Review: `templates/review_legacy_YYYYMMDD/` likewise.
3) Every PR must include a manual smoke checklist:
   - Start server: `python -m cli.faces_queue`, hard refresh browser.
   - Confirm `/api/people`, `/api/photos`, `/api/photo/<bucket>/faces` return JSON.
   - Verify no raw HTML error blobs appear in UI.
   - Verify “Back” view never traps you (falls back to front if missing).
     Face Queue expects `has_back/back_url` in the photo payload.

## PR order (do these in sequence)
PR1 — Pagination end-to-end (load more than 60 photos)
- Confirm backend supports pagination on `/api/photos?limit=&cursor=&priority`.
- Add "Load more" button (infinite scroll later).
- Persist `state.photo.cursor` + `state.photo.items`.
- When user reaches end via next/prev, auto-fetch next page (don’t jump scroll).
Definition of done: Grid grows 60 → 120 → 180 without losing selection or breaking
hero navigation.

PR2 — Fix scroll jump / half-scrolled page
- Identify scroll container (grid vs hero).
- On entering hero view: set hero viewport `scrollTop = 0`.
- On returning to grid: restore grid `scrollTop` (state already tracks conceptually).
- Ensure image load events don’t cause late layout shift.
Definition of done: switching photos, grid↔hero, or loading more never forces
manual scroll back up.

PR3 — Fast "select a person" flow
Pick one (smallest blast radius):
- Always-focused type-to-filter box when a face is selected.
- Pinned/Recent/Suggested label strip above full list.
- Hotkeys 1–9 for top pinned labels.
Definition of done: assigning a common person is < 2 seconds without scrolling.

PR4 — Reduce garbage detections (UI-side filtering)
- Slider/toggle for min confidence (default higher than current).
- Toggle for min face size (bbox area: w*h in normalized units).
- Toggle “Hide already-labeled faces”.
If backend payload lacks confidence, add to `/api/photo/<bucket>/faces` from SQLite.
Definition of done: false positives mostly hidden, with ability to lower filter.

PR5 — Photo priority triage
- Expose High/Normal/Low buttons in grid cards + hero header.
- Sort: High → Normal → Low.
- Add “Only High” filter.
Definition of done: set Low in 1 click and it leaves the working set.

## Runtime audit (required before PRs)
Create `docs/runtime_audit.md` with:
1) Live API examples (real payloads):
   - `GET /api/photos?limit=3`
   - `GET /api/photo/<bucket>/faces` (2–3 faces)
   - `GET /api/people` (first 20)
2) SQLite face table schema:
   - `PRAGMA table_info(face_detections);` (or actual table name)
3) Code map:
   - Where Photo Tagger grid renders and hero selection is controlled.
   - Where bbox mapping (object-fit contain math + ResizeObserver) lives.
   - Where Bucket Review zoom/pan + back rotations live (for selective porting).

## Optional: shared code extraction (only after PR1–PR5 stabilize)
Phase 1: copy helper code into shared modules without changing behavior:
- `photo_archive/static/lib/api_client.js`
- `photo_archive/static/lib/pref_store.js`
- `archive_lib/bucket_assets.py`

## Extra constraint
- No sidebar/people-list redesign until Photo Tagger flow is stable.

## Onboarding docs (if present)
- Start with `docs/reuse_map/00_FEATURE_MATRIX.md` for the at-a-glance feature map
  (front/back handling, overlay math, zoom/prefs, file ownership).
- Then read `docs/reuse_map/01_BUCKET_REVIEW_FLOW.md` and
  `docs/reuse_map/02_FACE_QUEUE_FLOW.md` for end-to-end flow narratives.
- Use `docs/reuse_map/_snippets/` for compact, high-signal code excerpts.
- If onboarding another assistant, hand them this bundle (in order):
  1) `docs/reuse_map/00_FEATURE_MATRIX.md`
  2) `docs/reuse_map/03_SHARED_COMPONENT_CANDIDATES.md` and
     `docs/reuse_map/04_BACKEND_REUSE_CANDIDATES.md`
  3) `docs/reuse_map/05_EXTRACTION_PLAN.md`
  4) `docs/reuse_map/_snippets/`
