// templates/review/review_app.js — keyboard J/K trigger next/prev bucket
function nextBucket() {
  flushNoteSave();
  if (state.index < state.visible.length - 1) {
    state.index += 1;
    render();
  }
}

function prevBucket() {
  flushNoteSave();
  if (state.index > 0) {
    state.index -= 1;
    render();
  }
}

// templates/faces_queue/queue_app.js — Photo Tagger prev/next photo and grid fallback
function stepPhotoSelection(delta) {
  const direction = Number(delta) || 0;
  if (!direction) return;
  if (state.photo.viewingGrid) {
    if (state.photo.items.length) {
      openPhotoHero(direction > 0 ? 0 : state.photo.items.length - 1);
    }
    return;
  }
  if (state.photo.selectedIndex === -1) {
    if (state.photo.items.length) {
      openPhotoHero(direction > 0 ? 0 : state.photo.items.length - 1);
    }
    return;
  }
  const nextIndex = state.photo.selectedIndex + direction;
  if (nextIndex < 0) {
    showPhotoGrid(true);
    return;
  }
  if (nextIndex >= state.photo.items.length) {
    if (state.photo.hasMore && !state.photo.loading) {
      setPhotoStatus('Loading more photos…');
      loadPhotoGrid();
    } else {
      setPhotoStatus('Reached end of loaded photos.', 'info');
    }
    return;
  }
  openPhotoHero(nextIndex);
}
