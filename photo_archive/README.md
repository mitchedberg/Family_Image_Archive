# Photo Archive Tooling

Python utilities supporting the Family Image Archive pipeline.

## Components
- `archive_lib/`: shared helpers (config, logging, hashing, imaging, db access, sidecars).
- `cli/`: Typer entry points for ingest/report/publish (only ingest implemented for v0).
- `scripts/init_db.py`: bootstrap SQLite schema in `02_WORKING_BUCKETS/db/archive.sqlite`.

## Quickstart
```
python -m scripts.init_db --db ../../02_WORKING_BUCKETS/db/archive.sqlite
python -m cli.ingest --root ../../01_INBOX/batch_0001_mom --source mom --dry-run
```

## Dependencies
Declared in `pyproject.toml`; install with `pip install -e .` inside `photo_archive/` once ready.

## Face Recognition

Use the `faces` CLI to generate YuNet/SFace embeddings for the raw originals and persist them in `face_embeddings`:

```
python -m cli.faces --source family_photos --limit 100 --min-score 0.5 --max-faces 8
```

Models download automatically into `03_MODELS/faces` the first time the command runs. Pass `--force` to rebuild embeddings for buckets that were already processed.

## Face Review UI

After embeddings exist you can launch the lightweight labeling tool:

```
python -m cli.faces_review --min-confidence 0.5
```

It generates `02_WORKING_BUCKETS/views/faces/` assets and writes assignments to `config/face_tags.csv`. Use the source chips and confidence slider to scope work, and click “Label”/“Clear” to manage names inline.

## Person Queue UI

Once you have (or want to create) labels, launch the single-face queue:

```
python -m cli.faces_queue --min-confidence 0.4 --min-similarity 0.45
```

The UI opens at `views/faces_queue/` and walks you through one bounding box at a time:

- **New person**: the tool pulls the highest-confidence unlabeled face, you type a name, press `T`/Enter, and that label is created in `config/face_tags.csv`.
- **Confirm matches**: after a label exists, the queue fetches nearest neighbours and asks “Is this X?” with hotkeys `T` (accept), `F` (reject), `S` (skip), `R` (refresh). Accepts go to `face_tags.csv`, rejects to `config/face_votes.csv` so they never surface again.
