// templates/review/review_app.js — compare mode toggles between AI and back views
function setCompareMode(mode) {
  if (mode !== 'ai' && mode !== 'back') {
    return;
  }
  state.compareMode = mode;
  localStorage.setItem('review_compare_mode', mode);
  updateCompareButtons();
  render();
}

// templates/faces_queue/queue_app.js — Photo Tagger back toggle for handwriting review
function handlePhotoBackToggle() {
  if (!state.photo.heroHasBack || !photoBackToggle) return;
  state.photo.viewingBack = !state.photo.viewingBack;
  const targetUrl = state.photo.viewingBack ? state.photo.heroBackUrl : state.photo.heroFrontUrl;
  updatePhotoBackToggle();
  updatePhotoOverlayToggle();
  if (!targetUrl) {
    state.photo.viewingBack = false;
    updatePhotoBackToggle();
    setPhotoStatus('Back image not available.', 'error');
    return;
  }
  setPhotoStatus(state.photo.viewingBack ? 'Loading back…' : 'Loading front…');
  renderPhotoHeroImage(targetUrl).then(() => setPhotoStatus(''));
}
