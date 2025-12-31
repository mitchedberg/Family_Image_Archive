#!/bin/bash
set -euo pipefail

ROOT="/Volumes/4TB_Sandisk_SSD/Family_Image_Archive"
APP_DIR="$ROOT/photo_archive"
LOG_DIR="$ROOT/02_WORKING_BUCKETS/logs"
mkdir -p "$LOG_DIR"
RUN_TS=$(date +%Y%m%dT%H%M%S)
LOG_FILE="$LOG_DIR/overnight_${RUN_TS}.log"
LOG_BASENAME=$(basename "$LOG_FILE")
PHASH_RUN_ID="overnight_${RUN_TS}"
PYTHON_BIN="$HOME/myenv/bin/python"


log_line() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" | tee -a "$LOG_FILE"
}

run_step() {
  local title=$1
  shift
  log_line "[run] $title"
  {
    echo "Command: $*"
    echo
    "$@"
  } 2>&1 | tee -a "$LOG_FILE"
}


cd "$APP_DIR"
log_line "Starting overnight run. Logs -> $LOG_FILE"

run_step "Assign negatives with img-token buckets" "$PYTHON_BIN" -m cli.assign --source negatives --log-level INFO
run_step "Regenerate negatives thumbnails" "$PYTHON_BIN" -m cli.thumbs --source negatives --force --log-level INFO
run_step "Resume Apple OCR (front/back, all sources)" "$PYTHON_BIN" -m cli.ocr --include-front --include-back --log-level INFO
run_step "Refresh negatives face embeddings" "$PYTHON_BIN" -m cli.faces --source negatives --force --log-level INFO
run_step "pHash duplicate report (${PHASH_RUN_ID})" "$PYTHON_BIN" -m cli.phash_dupes --db-readonly --apply --threshold 8 --run-id "$PHASH_RUN_ID" --log-level INFO

log_line "All overnight steps complete."
