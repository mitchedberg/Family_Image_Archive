#!/bin/zsh
set -euo pipefail

ROOT="/Volumes/4TB_Sandisk_SSD/Family_Image_Archive"
APP_DIR="$ROOT/photo_archive"
LOG_LEVEL="INFO"
REPORT_ROOT="$ROOT/02_WORKING_BUCKETS/reports/phash_test"

if [[ ! -d "$APP_DIR" ]]; then
  osascript -e 'display alert "Family Image Archive" message "Could not find photo_archive directory."' || true
  exit 1
fi

if command -v pyenv >/dev/null 2>&1; then
  eval "$(pyenv init -)" >/dev/null 2>&1 || true
  if pyenv versions --bare 2>/dev/null | grep -Fxq "myenv"; then
    pyenv shell myenv >/dev/null 2>&1 || true
  fi
fi

cd "$APP_DIR"

notify() {
  local msg
  msg=${1//\\/\\\\}
  msg=${msg//\"/\\\"}
  osascript -e "display notification \"$msg\" with title \"Family Image Archive\"" || true
}

build_applescript_list() {
  local entries=("$@")
  local parts=()
  local esc
  for entry in "${entries[@]}"; do
    esc=${entry//\\/\\\\}
    esc=${esc//"/\\"}
    parts+=("\"$esc\"")
  done
  local IFS=", "
  printf "%s" "${parts[*]}"
}

select_app() {
  osascript <<'OSA'
set appList to {"Bucket Review", "Bucket Review + Recorder", "Duplicate Reviewer", "Face Queue"}
set selectionChoice to choose from list appList with prompt "Which Family Image Archive tool do you want to launch?" default items {"Bucket Review"} with title "Family Image Archive"
if selectionChoice is false then
  return "CANCEL"
else
  return item 1 of selectionChoice
end if
OSA
}

select_scope() {
  osascript <<'OSA'
set scopeList to {"All sources (no filter)", "Family Photos only", "Negatives only", "Dad Slides only"}
set selectionChoice to choose from list scopeList with prompt "Which source should Bucket Review load?" default items {"Family Photos only"} with title "Bucket Review Scope"
if selectionChoice is false then
  return "CANCEL"
else
  return item 1 of selectionChoice
end if
OSA
}

select_variant_mode() {
  osascript <<'OSA'
set response to display dialog "Which buckets do you want to browse?" buttons {"AI only", "AI + Originals"} default button "AI + Originals" with title "Bucket Review Variants"
return button returned of response
OSA
}

select_limit() {
  osascript <<'OSA'
set dlg to display dialog "How many buckets should load?\nLeave blank (or enter 0) for all buckets." default answer "" buttons {"Continue"} default button "Continue" with title "Bucket Limit"
return text returned of dlg
OSA
}

launch_bucket_review() {
  scope=$(select_scope) || return 0
  if [[ "$scope" == "CANCEL" ]]; then
    return 0
  fi

  variant_choice=$(select_variant_mode) || return 0
  limit_input=$(select_limit) || return 0

  source_flag=()
  case "$scope" in
    "Family Photos only")
      source_flag=(--source family_photos)
      ;;
    "Negatives only")
      source_flag=(--source negatives)
      ;;
    "Dad Slides only")
      source_flag=(--source dad_slides)
      ;;
    *)
      source_flag=()
      ;;
  esac

  variant_flag=()
  if [[ "$variant_choice" == "AI + Originals" ]]; then
    variant_flag=(--include-all)
  fi

  limit_flag=()
  limit_trimmed=$(printf "%s" "$limit_input" | tr -d '[:space:]')
  if [[ -n "$limit_trimmed" ]]; then
    if [[ "$limit_trimmed" =~ ^[0-9]+$ ]]; then
      if [[ "$limit_trimmed" != "0" ]]; then
        limit_flag=(--limit "$limit_trimmed" --web-limit "$limit_trimmed")
      fi
    else
      osascript -e 'display alert "Bucket Review" message "Limit must be a whole number. Loading without limit."' || true
    fi
  fi

  cmd=(python -m cli.review "${source_flag[@]}" "${variant_flag[@]}" "${limit_flag[@]}" --log-level "$LOG_LEVEL")

  notify "Rebuilding previews… Bucket Review will open shortly."

  "${cmd[@]}"

  notify "Bucket Review server stopped."
}

select_phash_run() {
  local run_ids=("$@")
  if [[ ${#run_ids[@]} -eq 0 ]]; then
    osascript -e 'display alert "Duplicate Reviewer" message "No pHash runs found under reports/phash_test."' || true
    echo "CANCEL"
    return 1
  fi
  local list_literal
  list_literal=$(build_applescript_list "${run_ids[@]}")
  osascript <<OSA
set runList to {$list_literal}
set selectionChoice to choose from list runList with prompt "Select a pHash run to review" default items {item 1 of runList} with title "Duplicate Reviewer"
if selectionChoice is false then
  return "CANCEL"
else
  return item 1 of selectionChoice
end if
OSA
}

launch_phash_viewer() {
  if [[ ! -d "$REPORT_ROOT" ]]; then
    osascript -e 'display alert "Duplicate Reviewer" message "No reports/phash_test directory found. Run cli.phash_dupes first."' || true
    return 0
  fi

  local -a run_ids=()
  while IFS= read -r run_id; do
    [[ -n "$run_id" ]] && run_ids+=("$run_id")
  done < <(cd "$REPORT_ROOT" && ls -1t 2>/dev/null | head -n 20)

  if [[ ${#run_ids[@]} -eq 0 ]]; then
    osascript -e 'display alert "Duplicate Reviewer" message "No pHash runs available. Run cli.phash_dupes --apply first."' || true
    return 0
  fi

  local selected
  selected=$(select_phash_run "${run_ids[@]}") || return 0
  if [[ "$selected" == "CANCEL" ]]; then
    return 0
  fi

  notify "Launching Duplicate Reviewer for $selected…"
  python -m cli.phash_viewer --run-id "$selected"
  notify "Duplicate Reviewer closed."
}

launch_faces_queue() {
  notify "Launching Face Queue…"
  python -m cli.faces_queue --min-confidence 0.4 --min-similarity 0.45
  notify "Face Queue closed."
}

launch_voice_recorder() {
  local prep_cmd
  prep_cmd="cd \"$ROOT\"; "
  prep_cmd+="if [[ -f ~/.zshrc ]]; then source ~/.zshrc >/dev/null 2>&1 || true; fi; "
  prep_cmd+="python \"$ROOT/photo_voice_recorder.py\""
  local escaped=${prep_cmd//\"/\\\"}
  notify "Launching Voice Recorder…"
  osascript <<OSA
tell application "Terminal"
  do script "$escaped"
  activate
end tell
OSA
}

launch_bucket_and_recorder() {
  launch_voice_recorder
  sleep 2
  launch_bucket_review
}

app_choice=$(select_app)
if [[ "$app_choice" == "CANCEL" || -z "$app_choice" ]]; then
  exit 0
fi

case "$app_choice" in
  "Bucket Review")
    launch_bucket_review
    ;;
  "Bucket Review + Recorder")
    launch_bucket_and_recorder
    ;;
  "Duplicate Reviewer")
    launch_phash_viewer
    ;;
  "Face Queue")
    launch_faces_queue
    ;;
  *)
    exit 0
    ;;
 esac
