// templates/faces_queue/queue_app.js — overlay rendering + normalized bbox → pixels
function renderPhotoOverlay() {
  if (!state.photo.heroImageLoaded || !photoHeroOverlay || !photoHeroImage || !photoHeroImg) {
    if (photoHeroOverlay) {
      photoHeroOverlay.innerHTML = '';
      photoHeroOverlay.classList.toggle('is-hidden', true);
    }
    return;
  }
  const shouldShow = state.photo.showOverlays && !state.photo.viewingBack;
  photoHeroOverlay.classList.toggle('is-hidden', !shouldShow);
  if (!shouldShow) {
    photoHeroOverlay.innerHTML = '';
    return;
  }
  renderCandidateFacesOverlay(
    photoHeroOverlay,
    photoHeroImage,
    photoHeroImg,
    state.photo.faces || [],
    state.photo.activeFaceId
  );
}

function getRenderedImageRect(wrapper, img) {
  const wrapperRect = wrapper.getBoundingClientRect();
  const containerWidth = wrapperRect.width || 1;
  const containerHeight = wrapperRect.height || 1;
  const naturalWidth = img.naturalWidth || containerWidth;
  const naturalHeight = img.naturalHeight || containerHeight;
  const imageRatio = naturalWidth / naturalHeight || 1;
  const containerRatio = containerWidth / containerHeight || 1;
  let drawWidth = containerWidth;
  let drawHeight = containerHeight;
  if (imageRatio > containerRatio) {
    drawWidth = containerWidth;
    drawHeight = containerWidth / imageRatio;
  } else {
    drawHeight = containerHeight;
    drawWidth = containerHeight * imageRatio;
  }
  const offsetX = (containerWidth - drawWidth) / 2;
  const offsetY = (containerHeight - drawHeight) / 2;
  return { drawWidth, drawHeight, offsetX, offsetY };
}
