(function () {
  const DATA = window.FACE_QUEUE_DATA || {};

  const appEl = document.querySelector('.queue-app');
  const summaryEl = document.getElementById('summary');
  const labelSelect = document.getElementById('label-select');
  const similaritySlider = document.getElementById('similarity-slider');
  const similarityValue = document.getElementById('similarity-value');
  const newPersonBtn = document.getElementById('new-person-btn');
  const refreshBtn = document.getElementById('refresh-btn');
  const acceptBtn = document.getElementById('accept-btn');
  const rejectBtn = document.getElementById('reject-btn');
  const skipBtn = document.getElementById('skip-btn');
  const seedControls = document.getElementById('seed-controls');
  const seedInput = document.getElementById('seed-label-input');
  const seedSaveBtn = document.getElementById('seed-save-btn');
  const singleView = document.getElementById('single-view');
  const batchView = document.getElementById('batch-view');
  const modeIndicator = document.getElementById('mode-indicator');
  const labelSummaryEl = document.getElementById('label-summary');
  const viewSingleBtn = document.getElementById('view-single-btn');
  const viewBatchBtn = document.getElementById('view-batch-btn');
  const singleOnlyEls = document.querySelectorAll('.single-only');
  const legacyPanel = document.getElementById('legacy-panel');
  const legacyText = document.getElementById('legacy-text');
  const legacyChipRow = document.getElementById('legacy-chip-row');
  const insetCanvas = document.getElementById('face-crop');
  const insetCtx = insetCanvas?.getContext('2d') || null;
  const ignoreBtn = document.getElementById('ignore-btn');
  const ignoreReason = document.getElementById('ignore-reason');
  const crowdBtn = document.getElementById('crowd-btn');
  const batchGrid = document.getElementById('batch-grid');
  const batchCommitBtn = document.getElementById('batch-commit-btn');
  const batchRefreshBtn = document.getElementById('batch-refresh-btn');
  const batchClearBtn = document.getElementById('batch-clear-btn');
  const batchActions = document.getElementById('batch-actions');
  const auditList = document.getElementById('audit-list');
  const auditRefreshBtn = document.getElementById('audit-refresh-btn');
  const mergeOpenBtn = document.getElementById('merge-open-btn');
  const mergeDialog = document.getElementById('merge-dialog');
  const mergeSourceSelect = document.getElementById('merge-source');
  const mergeTargetSelect = document.getElementById('merge-target');
  const mergeConfirmBtn = document.getElementById('merge-confirm-btn');
  const mergeCancelBtn = document.getElementById('merge-cancel-btn');
  const mergeCloseBtn = document.getElementById('merge-close-btn');
  const mergeErrorEl = document.getElementById('merge-error');
  const undoBtn = document.getElementById('undo-btn');
  const labelList = document.getElementById('label-list');
  const labelFilterInput = document.getElementById('label-filter');
  const sidebarRefreshBtn = document.getElementById('sidebar-refresh-btn');
  const modePersonBtn = document.getElementById('mode-person-btn');
  const modePhotoBtn = document.getElementById('mode-photo-btn');
  const personModeSection = document.getElementById('person-mode');
  const photoModeSection = document.getElementById('photo-mode');
  const photoStatusEl = document.getElementById('photo-status');
  const photoGridView = document.getElementById('photo-grid-view');
  const photoHeroView = document.getElementById('photo-hero-view');
  const photoHeroImage = document.getElementById('photo-hero-image');
  const photoZoomCanvas = document.getElementById('photo-zoom-canvas');
  const photoHeroImg = document.getElementById('photo-hero-img');
  const photoHeroOverlay = document.getElementById('photo-hero-overlay');
  const photoHeroTitle = document.getElementById('photo-hero-title');
  const photoHeroSubtitle = document.getElementById('photo-hero-subtitle');
  const photoFaceList = document.getElementById('photo-face-list');
  const photoCounterEl = document.getElementById('photo-counter');
  const photoGridToggle = document.getElementById('photo-grid-toggle');
  const photoRefreshBtn = document.getElementById('photo-refresh-btn');
  const photoPrevBtn = document.getElementById('photo-prev-btn');
  const photoNextBtn = document.getElementById('photo-next-btn');
  const photoPriorityFilter = document.getElementById('photo-priority-filter');
  const photoMinConfidenceInput = document.getElementById('photo-min-confidence');
  const photoMinFaceAreaInput = document.getElementById('photo-min-face-area');
  const photoHideLabeledInput = document.getElementById('photo-hide-labeled');
  const photoLoadMoreBtn = document.getElementById('photo-load-more-btn');
  const photoGridFooter = document.getElementById('photo-grid-footer');
  const photoGridSummary = document.getElementById('photo-grid-summary');
  const photoPriorityToggle = document.getElementById('photo-priority-toggle');
  const photoBackToggle = document.getElementById('photo-back-toggle');
  const photoBackRotate = document.getElementById('photo-back-rotate');
  const photoOverlayToggle = document.getElementById('photo-overlay-toggle');
  const photoDrawToggle = document.getElementById('photo-draw-toggle');
  const photoRedetectBtn = document.getElementById('photo-redetect-btn');
  const photoZoomOutBtn = document.getElementById('photo-zoom-out');
  const photoZoomInBtn = document.getElementById('photo-zoom-in');
  const photoZoomSlider = document.getElementById('photo-zoom-slider');
  const photoZoomResetBtn = document.getElementById('photo-zoom-reset');
  const photoZoomLockBtn = document.getElementById('photo-zoom-lock');
  const photoZoomValue = document.getElementById('photo-zoom-value');
  const pageScrollEl = document.scrollingElement || document.documentElement;

  let suppressLabelChange = false;
  let cleanupCandidateOverlay = null;
  const HISTORY_LIMIT = 200;
  const PHOTO_DEFAULT_MIN_CONFIDENCE = 0.65;
  const PHOTO_DEFAULT_VARIANT = 'raw_front';
  const PHOTO_EMPTY_LOWER_THRESHOLD = 0.3;
  const PHOTO_DEFAULT_MIN_FACE_AREA = 0.003;
  const PHOTO_GRID_PAGE_SIZE = 60;
  const PHOTO_PRIORITY_ORDER = { high: 0, normal: 1, low: 2 };
  const PHOTO_ZOOM_MIN = 0.6;
  const PHOTO_ZOOM_MAX = 2.5;
  const PHOTO_DRAW_MIN_SIZE = 0.02;
  const MANUAL_FACE_PREFIX = 'manual:';
  const PHOTO_ZOOM_STORAGE_KEY = 'face_queue.photo.zoom';
  const PHOTO_ZOOM_LOCK_STORAGE_KEY = 'face_queue.photo.zoom_lock';
  const PHOTO_OVERLAY_STORAGE_KEY = 'face_queue.photo.overlay';

  function resetHistoryStacks() {
    if (!state.history) {
      state.history = { past: [], future: [] };
    }
    state.history.past = [];
    state.history.future = [];
  }

  function snapshotCandidate(candidate) {
    if (!candidate) return null;
    if (typeof structuredClone === 'function') {
      try {
        return structuredClone(candidate);
      } catch (error) {
        // ignore and fall back
      }
    }
    try {
      return JSON.parse(JSON.stringify(candidate));
    } catch (error) {
      return { ...candidate };
    }
  }

  function pushCurrentCandidateToHistory() {
    if (!hasHistorySupport() || !state.candidate) return;
    const clone = snapshotCandidate(state.candidate);
    if (!clone) return;
    state.history.past.push(clone);
    if (state.history.past.length > HISTORY_LIMIT) {
      state.history.past.shift();
    }
  }

  function hasHistorySupport() {
    return state.mode === 'verify' && state.view === 'single';
  }

  const state = {
    labels: DATA.labels || [],
    mode: 'idle', // seed | verify
    view: 'single', // single | batch
    activeLabel: '',
    similarity: clamp(parseFloat(DATA.default_similarity || '0.4')),
    candidate: null,
    unlabeledRemaining: DATA.unlabeled_remaining || 0,
    batch: {
      candidates: [],
      decisions: {},
    },
    ignoredTotal: DATA.ignored_total || 0,
    undoAvailable: Boolean(DATA.history_available),
    refreshPromise: null,
    people: {
      items: [],
      loading: false,
      error: '',
      query: '',
    },
    history: {
      past: [],
      future: [],
    },
    uiMode: 'person',
    photo: {
      loading: false,
      error: '',
      items: [],
      minConfidence: PHOTO_DEFAULT_MIN_CONFIDENCE,
      selectedIndex: -1,
      faces: [],
      allFaces: [],
      facesLoading: false,
      activeFaceId: '',
      overlayCleanup: null,
      viewingGrid: true,
      gridScrollTop: 0,
      pageScrollTop: 0,
      totalPhotos: 0,
      cursor: 0,
      nextCursor: null,
      hasMore: false,
      priorityFilter: 'all',
      gridController: null,
      heroController: null,
      heroImageToken: 0,
      heroMeta: null,
      heroImageLoaded: false,
      prioritySaving: false,
      heroFrontUrl: '',
      heroBackUrl: '',
      heroHasBack: false,
      viewingBack: false,
      emptyMessage: '',
      manualBoxes: [],
      transforms: { front: { rotate: 0 }, back: { rotate: 0 } },
      transformLoaded: false,
      minFaceArea: PHOTO_DEFAULT_MIN_FACE_AREA,
      hideLabeled: false,
      showOverlays: getStoredPreference(PHOTO_OVERLAY_STORAGE_KEY, 'true') !== 'false',
      zoom: clampZoom(parseFloat(getStoredPreference(PHOTO_ZOOM_STORAGE_KEY, '1')) || 1),
      panX: 0,
      panY: 0,
      suppressOverlayClick: false,
      lockZoom: getStoredPreference(PHOTO_ZOOM_LOCK_STORAGE_KEY, 'false') === 'true',
      drawMode: false,
      drawing: false,
      drawStart: null,
      drawBox: null,
      drawBoxEl: null,
      navLocked: false,
      navToken: 0,
    },
  };

  init();

  function init() {
    resetHistoryStacks();
    updateSummary();
    renderLabelOptions();
    setupControls();
    updatePhotoOverlayToggle();
    updatePhotoBackToggle();
    applyPhotoZoom();
    if (photoMinConfidenceInput) {
      photoMinConfidenceInput.value = state.photo.minConfidence.toFixed(2);
    }
    if (photoMinFaceAreaInput) {
      photoMinFaceAreaInput.value = state.photo.minFaceArea.toFixed(3);
    }
    if (photoHideLabeledInput) {
      photoHideLabeledInput.checked = state.photo.hideLabeled;
    }
    updatePhotoZoomLockUI();
    if (photoPriorityFilter) {
      photoPriorityFilter.value = state.photo.priorityFilter;
    }
    setAppMode('person');
    showPhotoGrid(true);
    loadPeopleRoster();
    updateUndoButtonState();
    if (state.labels.length) {
      activateLabel(state.labels[0].name);
    } else {
      startSeed();
    }
  }

  function setupControls() {
    if (similaritySlider) {
      similaritySlider.value = state.similarity.toFixed(2);
      updateSimilarityDisplay();
      similaritySlider.addEventListener('input', (event) => {
        state.similarity = clamp(parseFloat(event.target.value));
        updateSimilarityDisplay();
      });
    }
    newPersonBtn?.addEventListener('click', () => startSeed());
    refreshBtn?.addEventListener('click', () => {
      if (state.mode === 'verify') {
        fetchCandidate();
      } else {
        fetchSeedCandidate();
      }
    });
    acceptBtn?.addEventListener('click', () => {
      if (state.mode === 'verify') {
        handleDecision('accept');
      } else {
        submitSeedLabel();
      }
    });
    rejectBtn?.addEventListener('click', () => {
      if (state.mode === 'verify') {
        handleDecision('reject');
      }
    });
    skipBtn?.addEventListener('click', () => {
      if (state.mode === 'verify') {
        handleSkip();
      } else {
        fetchSeedCandidate();
      }
    });
    seedSaveBtn?.addEventListener('click', submitSeedLabel);
    labelSelect?.addEventListener('change', (event) => {
      if (suppressLabelChange) {
        return;
      }
      activateLabel(event.target.value);
    });
    document.addEventListener('keydown', handleHotkeys);
    ignoreBtn?.addEventListener('click', handleIgnore);
    crowdBtn?.addEventListener('click', handleCrowdIgnore);
    sidebarRefreshBtn?.addEventListener('click', () => {
      refreshLabelsFromServer();
      loadPeopleRoster();
    });
    if (labelFilterInput) {
      labelFilterInput.addEventListener('input', () => {
        state.people.query = normalizePeopleQuery(labelFilterInput.value);
        renderLabelList();
      });
      labelFilterInput.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
          if (labelFilterInput.value) {
            labelFilterInput.value = '';
          }
          if (state.people.query) {
            state.people.query = '';
            renderLabelList();
          }
        }
      });
    }
    viewSingleBtn?.addEventListener('click', () => setView('single'));
    viewBatchBtn?.addEventListener('click', () => setView('batch'));
    batchRefreshBtn?.addEventListener('click', () => loadBatchCandidates(true));
    batchClearBtn?.addEventListener('click', clearBatchDecisions);
    batchCommitBtn?.addEventListener('click', commitBatchDecisions);
    auditRefreshBtn?.addEventListener('click', () => refreshAudit(true));
    mergeOpenBtn?.addEventListener('click', openMergeDialog);
    mergeCancelBtn?.addEventListener('click', closeMergeDialog);
    mergeCloseBtn?.addEventListener('click', closeMergeDialog);
    mergeDialog?.addEventListener('click', (event) => {
      if (event.target === mergeDialog) {
        closeMergeDialog();
      }
    });
    mergeSourceSelect?.addEventListener('change', ensureMergeSelections);
    mergeTargetSelect?.addEventListener('change', ensureMergeSelections);
    mergeConfirmBtn?.addEventListener('click', submitLabelMerge);
    undoBtn?.addEventListener('click', handleUndo);
    modePersonBtn?.addEventListener('click', () => setAppMode('person'));
    modePhotoBtn?.addEventListener('click', () => setAppMode('photo'));
    photoRefreshBtn?.addEventListener('click', () => refreshPhotoGrid(true));
    photoGridToggle?.addEventListener('click', () => showPhotoGrid(true));
    photoPrevBtn?.addEventListener('click', () => stepPhotoSelection(-1));
    photoNextBtn?.addEventListener('click', () => stepPhotoSelection(1));
    photoHeroOverlay?.addEventListener('click', handlePhotoOverlayClick);
    photoFaceList?.addEventListener('click', handlePhotoFaceListClick);
    photoPriorityFilter?.addEventListener('change', handlePhotoPriorityFilterChange);
    if (photoMinConfidenceInput) {
      const handleConfidence = () => handlePhotoMinConfidenceChange(photoMinConfidenceInput.value);
      photoMinConfidenceInput.addEventListener('change', handleConfidence);
      photoMinConfidenceInput.addEventListener('blur', handleConfidence);
    }
    if (photoMinFaceAreaInput) {
      const handleArea = () => handlePhotoMinFaceAreaChange(photoMinFaceAreaInput.value);
      photoMinFaceAreaInput.addEventListener('change', handleArea);
      photoMinFaceAreaInput.addEventListener('blur', handleArea);
    }
    photoHideLabeledInput?.addEventListener('change', handlePhotoHideLabeledToggle);
    photoLoadMoreBtn?.addEventListener('click', () => loadPhotoGrid());
    photoOverlayToggle?.addEventListener('click', handlePhotoOverlayToggle);
    photoBackToggle?.addEventListener('click', handlePhotoBackToggle);
    photoBackRotate?.addEventListener('click', handlePhotoRotateClick);
    photoDrawToggle?.addEventListener('click', togglePhotoDrawMode);
    photoRedetectBtn?.addEventListener('click', handlePhotoRedetect);
    if (photoZoomSlider) {
      photoZoomSlider.value = clampZoom(state.photo.zoom).toFixed(2);
      photoZoomSlider.addEventListener('input', (event) => handlePhotoZoomSliderChange(event.target.value));
      photoZoomSlider.addEventListener('change', (event) => handlePhotoZoomSliderChange(event.target.value));
    }
    photoZoomOutBtn?.addEventListener('click', () => handlePhotoZoomAdjust(-0.1));
    photoZoomInBtn?.addEventListener('click', () => handlePhotoZoomAdjust(0.1));
    photoZoomResetBtn?.addEventListener('click', resetPhotoZoom);
    photoZoomLockBtn?.addEventListener('click', togglePhotoZoomLock);
    if (photoPriorityToggle) {
      photoPriorityToggle.querySelectorAll('button[data-photo-priority]').forEach((button) => {
        button.addEventListener('click', () => {
          const value = button.dataset.photoPriority;
          if (value) {
            setPhotoPriority(value);
          }
        });
      });
    }
    if (photoHeroImage) {
      photoHeroImage.addEventListener('wheel', handlePhotoWheelZoom, { passive: false });
      photoHeroImage.addEventListener('pointerdown', handlePhotoPanStart);
    }
    window.addEventListener('pointermove', handlePhotoPanMove);
    window.addEventListener('pointerup', handlePhotoPanEnd);
    window.addEventListener('pointercancel', handlePhotoPanEnd);
  }

  function setView(mode) {
    if (!state.activeLabel && mode === 'batch') {
      return;
    }
    state.view = mode;
    viewSingleBtn?.classList.toggle('is-active', mode === 'single');
    viewBatchBtn?.classList.toggle('is-active', mode === 'batch');
    if (mode === 'single') {
      singleView?.classList.remove('is-hidden');
      batchView?.classList.add('is-hidden');
      batchActions?.classList.add('is-hidden');
      singleOnlyEls.forEach((el) => el.classList.remove('is-hidden'));
    } else {
      batchView?.classList.remove('is-hidden');
      singleView?.classList.add('is-hidden');
      batchActions?.classList.remove('is-hidden');
      singleOnlyEls.forEach((el) => el.classList.add('is-hidden'));
      loadBatchCandidates(false);
    }
  }

  function startSeed() {
    resetHistoryStacks();
    state.mode = 'seed';
    state.activeLabel = '';
    updateLabelSummary();
    renderLabelList();
    setView('single');
    disableDecisionButtons(true);
    toggleSeedControls(true);
    state.candidate = null;
    updateModeText('Label a new person.');
    renderMessage('Loading…');
    fetchSeedCandidate();
  }

  function startVerify() {
    if (!state.activeLabel) {
      renderMessage('Select a label or start a new person.');
      return;
    }
    resetHistoryStacks();
    state.candidate = null;
    state.mode = 'verify';
    toggleSeedControls(false);
    updateModeText(`Confirm matches for ${state.activeLabel}.`);
    renderMessage('Loading…');
    fetchCandidate();
    refreshAudit();
  }

  function fetchSeedCandidate() {
    fetch('/api/queue/seed')
      .then(checkResponse)
      .then((payload) => {
        if (payload.status === 'empty') {
          state.unlabeledRemaining = 0;
          renderMessage('No unlabeled faces remaining. Continue reviewing existing labels.');
          updateSummary();
          return;
        }
        state.candidate = payload.candidate;
        renderCandidate();
        const suggestions = (state.candidate.legacy_names || []).filter(Boolean);
        seedInput.value = suggestions[0] || '';
        seedInput.focus();
        updateSummary();
      })
      .catch((error) => renderMessage(error.message || 'Failed to fetch seed face.'));
  }

  function submitSeedLabel() {
    if (!state.candidate) return;
    const label = (seedInput.value || '').trim();
    if (!label) {
      seedInput.focus();
      return;
    }
    fetch('/api/queue/seed', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ face_id: state.candidate.face_id, label }),
    })
      .then(checkResponse)
      .then(() => {
        state.undoAvailable = true;
        updateUndoButtonState();
        seedInput.value = '';
        return refreshLabelsFromServer();
      })
      .then(() => {
        activateLabel(label);
      })
      .catch((error) => renderMessage(error.message || 'Failed to save label.'));
  }

  function fetchCandidate() {
    if (!state.activeLabel) {
      renderMessage('Select a label or start a new person.');
      return;
    }
    disableDecisionButtons(true);
    const params = new URLSearchParams({
      label: state.activeLabel,
      min_similarity: state.similarity.toFixed(2),
    });
    fetch(`/api/queue/next?${params.toString()}`)
      .then(checkResponse)
      .then((payload) => {
        if (payload.status === 'empty') {
          renderMessage('No matches above the similarity threshold. Pulling a new face to seed…');
          startSeed();
          return;
        }
        if (hasHistorySupport() && state.candidate && state.candidate.face_id !== payload.candidate.face_id) {
          pushCurrentCandidateToHistory();
          state.history.future = [];
        }
        state.candidate = payload.candidate;
        renderCandidate();
        disableDecisionButtons(false);
      })
      .catch((error) => renderMessage(error.message || 'Failed to fetch candidate.'));
  }

  function handleDecision(type) {
    if (!state.candidate || !state.activeLabel) return;
    const endpoint = type === 'accept' ? '/api/queue/accept' : '/api/queue/reject';
    disableDecisionButtons(true);
    fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        face_id: state.candidate.face_id,
        label: state.activeLabel,
      }),
    })
      .then(checkResponse)
      .then(() => {
        state.undoAvailable = true;
        updateUndoButtonState();
        return refreshLabelsFromServer();
      })
      .then(() => {
        refreshAudit(true);
        fetchCandidate();
      })
      .catch((error) => renderMessage(error.message || 'Failed to save decision.'));
  }

  function handleIgnore() {
    if (!state.candidate) return;
    disableDecisionButtons(true);
    ignoreBtn?.setAttribute('disabled', 'true');
    fetch('/api/queue/ignore', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        face_id: state.candidate.face_id,
        reason: ignoreReason?.value || 'background',
      }),
    })
      .then(checkResponse)
      .then(() => {
        state.undoAvailable = true;
        updateUndoButtonState();
        return refreshLabelsFromServer();
      })
      .then(() => {
        fetchCandidate();
      })
      .catch((error) => renderMessage(error.message || 'Failed to ignore face.'))
      .finally(() => {
        ignoreBtn?.removeAttribute('disabled');
      });
  }

  function handleCrowdIgnore() {
    if (!state.candidate || !state.candidate.bucket_prefix) return;
    crowdBtn?.setAttribute('disabled', 'true');
    disableDecisionButtons(true);
    fetch('/api/queue/crowd', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: state.candidate.bucket_prefix,
        reason: ignoreReason?.value || 'crowd',
      }),
    })
      .then(checkResponse)
      .then(() => {
        state.undoAvailable = true;
        updateUndoButtonState();
        return refreshLabelsFromServer();
      })
      .then(() => {
        fetchCandidate();
      })
      .catch((error) => renderMessage(error.message || 'Failed to ignore crowd.'))
      .finally(() => {
        crowdBtn?.removeAttribute('disabled');
      });
  }

  function handleSkip() {
    if (state.mode !== 'verify') {
      fetchSeedCandidate();
      return;
    }
    if (navigateHistoryForward()) {
      return;
    }
    if (!state.candidate || !state.activeLabel) {
      fetchCandidate();
      return;
    }
    disableDecisionButtons(true);
    fetch('/api/queue/skip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        face_id: state.candidate.face_id,
        label: state.activeLabel,
      }),
    })
      .then(checkResponse)
      .then(() => {
        fetchCandidate();
      })
      .catch((error) => {
        renderMessage(error.message || 'Failed to skip face.');
        disableDecisionButtons(false);
      });
  }

  function handleUndo() {
    if (undoBtn) {
      undoBtn.disabled = true;
    }
    disableDecisionButtons(true);
    fetch('/api/queue/undo', { method: 'POST' })
      .then(checkResponse)
      .then((payload) => {
        if (payload.status === 'empty') {
          state.undoAvailable = false;
          updateUndoButtonState();
          renderMessage('Nothing left to undo.');
          disableDecisionButtons(false);
          return;
        }
        state.undoAvailable = Boolean(payload.history_available);
        updateUndoButtonState();
        if (Array.isArray(payload.labels)) {
          state.labels = payload.labels;
          renderLabelOptions();
        }
        if (typeof payload.unlabeled_remaining === 'number') {
          state.unlabeledRemaining = payload.unlabeled_remaining;
        }
        if (typeof payload.ignored_total === 'number') {
          state.ignoredTotal = payload.ignored_total;
        }
        updateSummary();
        resetHistoryStacks();
        if (payload.restored_face) {
          state.candidate = payload.restored_face;
          renderCandidate();
          disableDecisionButtons(false);
        } else {
          fetchCandidate();
        }
      })
      .catch((error) => {
        renderMessage(error.message || 'Failed to undo.');
        disableDecisionButtons(false);
        updateUndoButtonState();
      });
  }

  function renderCandidate() {
    if (!singleView || !state.candidate) return;
    if (cleanupCandidateOverlay) {
      cleanupCandidateOverlay();
      cleanupCandidateOverlay = null;
    }
    singleView.innerHTML = '';
    const wrapper = document.createElement('div');
    wrapper.className = 'candidate-layout';

    const imageCol = document.createElement('div');
    imageCol.className = 'candidate-layout__image';
    const candidateImage = document.createElement('div');
    candidateImage.className = 'candidate-image';
    const img = document.createElement('img');
    img.src = state.candidate.image;
    img.alt = `Bucket ${state.candidate.bucket_prefix}`;
    candidateImage.appendChild(img);
    const overlayLayer = document.createElement('div');
    overlayLayer.className = 'candidate-image__overlay';
    candidateImage.appendChild(overlayLayer);
    imageCol.appendChild(candidateImage);
    wrapper.appendChild(imageCol);

    const detailCol = document.createElement('div');
    detailCol.className = 'candidate-layout__details';
    detailCol.appendChild(legacyPanel);
    const faceInset = document.createElement('div');
    faceInset.className = 'candidate-face';
    faceInset.appendChild(insetCanvas);
    const labelEl = document.createElement('div');
    labelEl.className = 'candidate-face__label';
    labelEl.textContent = 'Inset';
    faceInset.appendChild(labelEl);
    detailCol.appendChild(faceInset);

    const metaList = document.createElement('ul');
    metaList.className = 'candidate-meta';
    const metaPairs = [
      ['Bucket', state.candidate.bucket_prefix],
      ['Source', state.candidate.bucket_source],
      ['Confidence', state.candidate.confidence.toFixed(2)],
      [
        'Similarity',
        typeof state.candidate.similarity === 'number' ? state.candidate.similarity.toFixed(2) : '—',
      ],
    ];
    metaPairs.forEach(([label, value]) => {
      const li = document.createElement('li');
      const span = document.createElement('span');
      span.textContent = `${label}:`;
      const strong = document.createElement('strong');
      strong.textContent = value;
      li.appendChild(span);
      li.appendChild(strong);
      metaList.appendChild(li);
    });
    detailCol.appendChild(metaList);
    wrapper.appendChild(detailCol);
    singleView.appendChild(wrapper);

    const bbox = state.candidate.bbox || state.candidate.bbox_xywh || {};
    const activeFace = [
      {
        face_id: state.candidate.face_id,
        bbox,
        state: { label: state.activeLabel },
      },
    ];
    const renderActiveOverlay = () =>
      renderCandidateFacesOverlay(overlayLayer, candidateImage, img, activeFace, state.candidate.face_id);
    if (img.complete) {
      renderActiveOverlay();
    } else {
      img.addEventListener('load', renderActiveOverlay, { once: true });
    }

    const faceId = state.candidate.face_id;
    fetch(`/api/face/${encodeURIComponent(faceId)}/context`)
      .then(checkResponse)
      .then((context) => {
        if (!state.candidate || state.candidate.face_id !== faceId) return;
        const faces = Array.isArray(context.faces)
          ? context.faces.map((face) => ({
              ...face,
              bbox: face.bbox || face.bbox_xywh || face.bbox,
            }))
          : [];
        if (!faces.length) {
          renderActiveOverlay();
          return;
        }
        const targetId = context.face?.face_id || faceId;
        const rerender = () => renderCandidateFacesOverlay(overlayLayer, candidateImage, img, faces, targetId);
        rerender();
        const resizeHandlers = [];
        const resizeListener = () => rerender();
        window.addEventListener('resize', resizeListener);
        resizeHandlers.push(() => window.removeEventListener('resize', resizeListener));
        if (window.ResizeObserver) {
          const observer = new ResizeObserver(() => rerender());
          observer.observe(candidateImage);
          resizeHandlers.push(() => observer.disconnect());
        }
        cleanupCandidateOverlay = () => {
          resizeHandlers.forEach((fn) => {
            try {
              fn();
            } catch (error) {
              console.warn('Failed to clean overlay resize handler', error);
            }
          });
          cleanupCandidateOverlay = null;
        };
      })
      .catch(() => {
        renderActiveOverlay();
      });

    drawFaceInset(img, bbox);
    renderLegacyPanel();
  }

  function renderMessage(text) {
    if (!singleView) return;
    singleView.innerHTML = `<p class="empty">${text}</p>`;
    if (legacyPanel) legacyPanel.classList.add('is-hidden');
  }

  function renderLegacyPanel() {
    if (!legacyPanel || !legacyText || !legacyChipRow) return;
    const names = (state.candidate?.legacy_names || []).filter(Boolean);
    if (!names.length) {
      legacyPanel.classList.add('is-hidden');
      legacyChipRow.innerHTML = '';
      return;
    }
    if (state.mode === 'seed') {
      legacyText.textContent = 'Apple Photos suggests:';
      legacyChipRow.innerHTML = '';
      names.forEach((name) => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = name;
        btn.addEventListener('click', () => {
          seedInput.value = name;
          seedInput.focus();
          seedInput.select();
        });
        legacyChipRow.appendChild(btn);
      });
      legacyChipRow.classList.remove('is-hidden');
    } else {
      legacyText.textContent = `Apple Photos tagged: ${names.join(', ')}`;
      legacyChipRow.innerHTML = '';
    }
    legacyPanel.classList.remove('is-hidden');
  }

  function disableDecisionButtons(value) {
    [acceptBtn, rejectBtn, skipBtn].forEach((btn) => {
      if (btn) btn.disabled = value;
    });
  }

  function updateUndoButtonState() {
    if (!undoBtn) return;
    undoBtn.disabled = !state.undoAvailable;
  }

  function toggleSeedControls(show) {
    if (!seedControls) return;
    seedControls.classList.toggle('is-hidden', !show);
    acceptBtn.textContent = show ? 'Save Label (T)' : 'Accept (T)';
  }

  function updateModeText(text) {
    if (modeIndicator) modeIndicator.textContent = text;
  }

  function updateSummary() {
    if (!summaryEl) return;
    const totalLabels = state.labels.reduce((sum, entry) => sum + entry.count, 0);
    summaryEl.textContent = `${totalLabels.toLocaleString()} labeled faces · ${
      DATA.total_faces?.toLocaleString() || '0'
    } detections total · ${state.unlabeledRemaining.toLocaleString()} unlabeled · ${state.ignoredTotal.toLocaleString()} ignored`;
    updateLabelSummary();
  }

  function updateLabelSummary() {
    if (!labelSummaryEl) return;
    if (!state.activeLabel) {
      labelSummaryEl.textContent = 'No label selected.';
      return;
    }
    const count = getLabelCount(state.activeLabel);
    labelSummaryEl.textContent = `${state.activeLabel}: ${count} confirmed faces`;
  }

  function renderLabelOptions() {
    if (!labelSelect) return;
    suppressLabelChange = true;
    labelSelect.innerHTML = '';
    if (!state.labels.length) {
      const option = document.createElement('option');
      option.value = '';
      option.textContent = 'No labels yet — start a new person.';
      option.disabled = true;
      option.selected = true;
      labelSelect.appendChild(option);
      labelSelect.disabled = true;
      updateMergeButtonState();
      suppressLabelChange = false;
      return;
    }
    labelSelect.disabled = false;
    let activeExists = state.labels.some((entry) => entry.name === state.activeLabel);
    if (!activeExists) {
      state.activeLabel = state.labels[0]?.name || '';
    }
    state.labels.forEach((entry) => {
      const option = document.createElement('option');
      option.value = entry.name;
      option.textContent = `${entry.name} (${entry.count})`;
      option.selected = entry.name === state.activeLabel;
      labelSelect.appendChild(option);
    });
    if (state.activeLabel) {
      labelSelect.value = state.activeLabel;
    }
    suppressLabelChange = false;
    updateMergeButtonState();
    if (isMergeDialogVisible()) {
      populateMergeOptions();
      ensureMergeSelections();
    }
    renderLabelList();
  }

  function loadPeopleRoster() {
    if (!labelList) return;
    state.people.loading = true;
    state.people.error = '';
    renderLabelList();
    fetch('/api/people')
      .then(checkResponse)
      .then((payload) => {
        const roster = normalizePeoplePayload(payload);
        state.people.items = roster;
        state.people.loading = false;
        state.people.error = '';
        renderLabelList();
      })
      .catch((error) => {
        state.people.loading = false;
        state.people.error = error?.message || 'Failed to load people.';
        renderLabelList();
      });
  }

  function renderLabelList() {
    if (!labelList) return;
    labelList.innerHTML = '';
    if (state.people.loading) {
      labelList.innerHTML = '<p class="empty">Loading people…</p>';
      return;
    }
    if (state.people.error) {
      const wrapper = document.createElement('div');
      wrapper.className = 'people-error';
      const msg = document.createElement('p');
      msg.className = 'empty';
      msg.textContent = state.people.error;
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.textContent = 'Retry';
      retry.addEventListener('click', () => loadPeopleRoster());
      wrapper.appendChild(msg);
      wrapper.appendChild(retry);
      labelList.appendChild(wrapper);
      return;
    }
    const roster = Array.isArray(state.people.items) && state.people.items.length ? state.people.items : null;
    if (roster) {
      const filteredRoster = filterPeopleRoster(roster);
      if (!filteredRoster.length) {
        renderPeopleEmptyMessage('No people match your filter.');
        return;
      }
      filteredRoster.forEach((person) => {
        const button = createPeopleRowButton(person);
        labelList.appendChild(button);
      });
      return;
    }
    if (!state.labels.length) {
      labelList.innerHTML = '<p class="empty">No labels yet — add someone with “New Person”.</p>';
      return;
    }
    const filteredLabels = filterLabelEntries(state.labels);
    if (!filteredLabels.length) {
      renderPeopleEmptyMessage('No labels match your filter.');
      return;
    }
    filteredLabels.forEach((entry) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'label-item';
      if (entry.name === state.activeLabel) {
        button.classList.add('is-active');
      }
      const nameWrap = document.createElement('div');
      nameWrap.className = 'label-item__name';
      const nameEl = document.createElement('strong');
      nameEl.textContent = entry.name;
      const countEl = document.createElement('span');
      countEl.textContent = `${Number(entry.count || 0).toLocaleString()} faces`;
      nameWrap.appendChild(nameEl);
      nameWrap.appendChild(countEl);

      const signals = document.createElement('div');
      signals.className = 'label-item__signals';
      const totalEl = document.createElement('span');
      totalEl.className = 'label-item__count';
      totalEl.textContent = Number(entry.count || 0).toLocaleString();
      signals.appendChild(totalEl);
      if (Number(entry.pending || 0) > 0) {
        const dot = document.createElement('span');
        dot.className = 'label-item__dot';
        signals.appendChild(dot);
      }

      button.appendChild(nameWrap);
      button.appendChild(signals);
      button.addEventListener('click', () => activateLabel(entry.name));
      labelList.appendChild(button);
    });
  }

  function renderPeopleEmptyMessage(text) {
    const message = document.createElement('p');
    message.className = 'empty';
    message.textContent = text;
    labelList.appendChild(message);
  }

  function filterPeopleRoster(roster) {
    const query = normalizePeopleQuery(state.people.query);
    if (!query) return roster;
    return roster.filter((person) => {
      const label = person?.label || person?.name || '';
      const group = person?.group || '';
      const haystack = `${label} ${group}`.toLowerCase();
      return haystack.includes(query);
    });
  }

  function filterLabelEntries(entries) {
    const query = normalizePeopleQuery(state.people.query);
    if (!query) return entries;
    return entries.filter((entry) => {
      const name = entry?.name || '';
      const haystack = name.toLowerCase();
      return haystack.includes(query);
    });
  }

  function normalizePeopleQuery(value) {
    return (value || '').toString().trim().toLowerCase();
  }

  function createPeopleRowButton(entry) {
    const label = entry.label || entry.name || '';
    if (!label) return document.createElement('div');
    const count = Number(entry.face_count ?? entry.count ?? 0);
    const pending = Number(entry.pending_count ?? entry.pending ?? 0);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'label-item';
    if (label === state.activeLabel) {
      button.classList.add('is-active');
    }
    const nameWrap = document.createElement('div');
    nameWrap.className = 'label-item__name';
    const nameEl = document.createElement('strong');
    nameEl.textContent = label || 'Unnamed';
    const countEl = document.createElement('span');
    countEl.textContent = `${count.toLocaleString()} faces`;
    nameWrap.appendChild(nameEl);
    nameWrap.appendChild(countEl);
    const signals = document.createElement('div');
    signals.className = 'label-item__signals';
    const totalEl = document.createElement('span');
    totalEl.className = 'label-item__count';
    totalEl.textContent = count.toLocaleString();
    signals.appendChild(totalEl);
    if (pending > 0) {
      const dot = document.createElement('span');
      dot.className = 'label-item__dot';
      signals.appendChild(dot);
    }
    button.appendChild(nameWrap);
    button.appendChild(signals);
    button.addEventListener('click', () => activateLabel(label));
    return button;
  }

  function activateLabel(labelName) {
    if (!labelName) {
      return;
    }
    state.activeLabel = labelName;
    if (labelSelect) {
      suppressLabelChange = true;
      labelSelect.value = labelName;
      suppressLabelChange = false;
      if (document.activeElement === labelSelect) {
        labelSelect.blur();
      }
    }
    state.batch.decisions = {};
    state.batch.candidates = [];
    resetHistoryStacks();
    state.candidate = null;
    updateLabelSummary();
    renderLabelList();
    if (state.uiMode === 'photo') {
      setPhotoStatus(`Assign faces to ${state.activeLabel}.`);
      renderPhotoFaceList();
    }
    if (state.view === 'batch') {
      loadBatchCandidates(true);
    } else {
      startVerify();
    }
  }

  function refreshLabelsFromServer() {
    if (state.refreshPromise) {
      return state.refreshPromise;
    }
    const request = fetch('/api/labels')
      .then(checkResponse)
      .then((payload) => {
        if (Array.isArray(payload.labels)) {
          const previous = state.activeLabel;
          state.labels = payload.labels;
          const stillExists = state.labels.some((entry) => entry.name === previous);
          if (!stillExists) {
            state.activeLabel = state.labels[0]?.name || '';
          }
          renderLabelOptions();
          if (state.activeLabel && state.activeLabel !== previous && state.mode === 'verify') {
            activateLabel(state.activeLabel);
            return payload;
          }
        }
        if (typeof payload.unlabeled_remaining === 'number') {
          state.unlabeledRemaining = payload.unlabeled_remaining;
        }
        if (typeof payload.ignored_total === 'number') {
          state.ignoredTotal = payload.ignored_total;
        }
        if (typeof payload.history_available === 'boolean') {
          state.undoAvailable = payload.history_available;
          updateUndoButtonState();
        }
        updateSummary();
        return payload;
      })
      .finally(() => {
        state.refreshPromise = null;
      });
    state.refreshPromise = request;
    return request;
  }

  function getLabelCount(label) {
    const entry = state.labels.find((item) => item.name === label);
    return entry ? entry.count : 0;
  }

  function loadBatchCandidates(force) {
    if (!state.activeLabel) return;
    if (!force && state.batch.candidates.length) {
      renderBatchGrid();
      return;
    }
    batchGrid.innerHTML = '<p class="empty">Loading batch…</p>';
    fetch('/api/queue/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        label: state.activeLabel,
        limit: 15,
        min_similarity: state.similarity.toFixed(2),
      }),
    })
      .then(checkResponse)
      .then((payload) => {
        state.batch.candidates = payload.candidates || [];
        state.batch.decisions = {};
        renderBatchGrid();
      })
      .catch((error) => {
        batchGrid.innerHTML = `<p class="empty">${error.message || 'Failed to load batch.'}</p>`;
      });
  }

  function normalizePeoplePayload(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) {
      return payload;
    }
    if (Array.isArray(payload.people)) {
      return payload.people;
    }
    if (Array.isArray(payload.labels)) {
      return payload.labels;
    }
    if (Array.isArray(payload.items)) {
      return payload.items;
    }
    return [];
  }

  function normalizePhotoPayload(payload) {
    if (!payload) return [];
    if (Array.isArray(payload)) {
      return payload;
    }
    if (Array.isArray(payload.photos)) {
      return payload.photos;
    }
    if (Array.isArray(payload.items)) {
      return payload.items;
    }
    if (Array.isArray(payload.groups)) {
      return payload.groups;
    }
    return [];
  }

  function renderBatchGrid() {
    if (!state.batch.candidates.length) {
      batchGrid.innerHTML = '<p class="empty">No batch candidates. Try lowering similarity or refresh.</p>';
      batchCommitBtn.disabled = true;
      return;
    }
    batchGrid.innerHTML = '';
    state.batch.candidates.forEach((candidate) => {
      const card = document.createElement('div');
      card.className = 'batch-card';
      card.dataset.faceId = candidate.face_id;

      const imageWrap = document.createElement('div');
      imageWrap.className = 'batch-card__image';
      const img = document.createElement('img');
      img.src = candidate.image;
      img.alt = candidate.bucket_prefix;
      imageWrap.appendChild(img);
      const box = document.createElement('div');
      box.className = 'candidate-image__box';
      imageWrap.appendChild(box);
      card.appendChild(imageWrap);

      const meta = document.createElement('div');
      meta.className = 'batch-card__meta';
      meta.innerHTML = `<span>${candidate.bucket_source}</span><strong>${
        typeof candidate.similarity === 'number' ? candidate.similarity.toFixed(2) : '—'
      }</strong>`;
      card.appendChild(meta);

      const actions = document.createElement('div');
      actions.className = 'batch-card__actions';
      const acceptBtn = document.createElement('button');
      acceptBtn.type = 'button';
      acceptBtn.textContent = 'Accept';
      const rejectBtn = document.createElement('button');
      rejectBtn.type = 'button';
      rejectBtn.textContent = 'Reject';
      actions.appendChild(acceptBtn);
      actions.appendChild(rejectBtn);
      card.appendChild(actions);
      batchGrid.appendChild(card);

      const bbox = candidate.bbox || {};
      const position = () => positionBoundingBox(imageWrap, img, box, bbox);
      if (img.complete) {
        position();
      } else {
        img.addEventListener('load', position, { once: true });
      }

      acceptBtn.addEventListener('click', () => setBatchDecision(candidate.face_id, 'accept', card));
      rejectBtn.addEventListener('click', () => setBatchDecision(candidate.face_id, 'reject', card));
      const decision = state.batch.decisions[candidate.face_id];
      if (decision) {
        card.classList.toggle('is-accept', decision === 'accept');
        card.classList.toggle('is-reject', decision === 'reject');
      }
    });
    updateBatchCommitState();
  }

  function setBatchDecision(faceId, decision, card) {
    if (!faceId) return;
    if (state.batch.decisions[faceId] === decision) {
      delete state.batch.decisions[faceId];
    } else {
      state.batch.decisions[faceId] = decision;
    }
    if (card) {
      card.classList.toggle('is-accept', state.batch.decisions[faceId] === 'accept');
      card.classList.toggle('is-reject', state.batch.decisions[faceId] === 'reject');
      if (!state.batch.decisions[faceId]) {
        card.classList.remove('is-accept', 'is-reject');
      }
    }
    updateBatchCommitState();
  }

  function updateBatchCommitState() {
    const hasDecision = Object.keys(state.batch.decisions).length > 0;
    batchCommitBtn.disabled = !hasDecision;
  }

  function clearBatchDecisions() {
    state.batch.decisions = {};
    renderBatchGrid();
  }

  function commitBatchDecisions() {
    const acceptIds = Object.keys(state.batch.decisions).filter((id) => state.batch.decisions[id] === 'accept');
    const rejectIds = Object.keys(state.batch.decisions).filter((id) => state.batch.decisions[id] === 'reject');
    if (!acceptIds.length && !rejectIds.length) return;
    batchCommitBtn.disabled = true;
    fetch('/api/queue/batch/commit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        label: state.activeLabel,
        accept_ids: acceptIds,
        reject_ids: rejectIds,
      }),
    })
      .then(checkResponse)
      .then(() => {
        if (acceptIds.length || rejectIds.length) {
          state.undoAvailable = true;
          updateUndoButtonState();
        }
        state.batch.decisions = {};
        state.batch.candidates = [];
        return refreshLabelsFromServer();
      })
      .then(() => {
        refreshAudit(true);
        loadBatchCandidates(true);
      })
      .catch((error) => {
        batchGrid.insertAdjacentHTML('beforeend', `<p class="empty">${error.message || 'Batch commit failed.'}</p>`);
      })
      .finally(() => updateBatchCommitState());
  }

  function refreshAudit(force) {
    if (!state.activeLabel) {
      auditList.innerHTML = '<p class="empty">Select a label to see confirmed faces.</p>';
      return;
    }
    if (!force && auditList.dataset.label === state.activeLabel) {
      return;
    }
    auditList.innerHTML = '<p class="empty">Loading…</p>';
    auditList.dataset.label = state.activeLabel;
    const params = new URLSearchParams({ label: state.activeLabel });
    fetch(`/api/labels/detail?${params.toString()}`)
      .then(checkResponse)
      .then((payload) => {
        renderAudit(payload.faces || []);
      })
      .catch((error) => {
        auditList.innerHTML = `<p class="empty">${error.message || 'Failed to load confirmed faces.'}</p>`;
      });
  }

  function renderAudit(faces) {
    if (!faces.length) {
      auditList.innerHTML = '<p class="empty">No confirmed faces yet.</p>';
      return;
    }
    auditList.innerHTML = '';
    faces.forEach((face) => {
      const card = document.createElement('div');
      card.className = 'audit-face';
      const media = document.createElement('div');
      media.className = 'audit-face__image';
      const img = document.createElement('img');
      img.src = face.image;
      img.alt = face.bucket_prefix;
      const box = document.createElement('div');
      box.className = 'candidate-image__box';
      media.appendChild(img);
      media.appendChild(box);
      card.appendChild(media);
      const meta = document.createElement('div');
      meta.className = 'batch-card__meta';
      meta.innerHTML = `<span>${face.bucket_source}</span><strong>${
        face.updated_at ? new Date(face.updated_at).toLocaleDateString() : ''
      }</strong>`;
      card.appendChild(meta);
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = 'Remove';
      button.addEventListener('click', () => removeAuditFace(face.face_id));
      card.appendChild(button);
      auditList.appendChild(card);

      const bbox = face.bbox || {};
      const position = () => positionBoundingBox(media, img, box, bbox);
      if (img.complete) {
        position();
      } else {
        img.addEventListener('load', position, { once: true });
      }
    });
  }

  function removeAuditFace(faceId) {
    if (!state.activeLabel || !faceId) return;
    fetch('/api/labels/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ label: state.activeLabel, face_id: faceId }),
    })
      .then(checkResponse)
      .then(() => refreshLabelsFromServer())
      .then(() => {
        refreshAudit(true);
      })
      .catch((error) => {
        alert(error.message || 'Failed to remove face.'); // eslint-disable-line no-alert
      });
  }

  function openMergeDialog() {
    if (!mergeDialog || state.labels.length < 2) return;
    populateMergeOptions();
    ensureMergeSelections();
    setMergeError('');
    mergeDialog.classList.remove('is-hidden');
    mergeDialog.setAttribute('aria-hidden', 'false');
    setTimeout(() => mergeSourceSelect?.focus(), 0);
  }

  function closeMergeDialog() {
    if (!mergeDialog) return;
    mergeDialog.classList.add('is-hidden');
    mergeDialog.setAttribute('aria-hidden', 'true');
    setMergeError('');
    if (mergeConfirmBtn) {
      mergeConfirmBtn.disabled = false;
    }
  }

  function populateMergeOptions() {
    if (!mergeSourceSelect || !mergeTargetSelect) return;
    const sourceDefault = state.activeLabel || (state.labels[0]?.name || '');
    const targetDefault =
      state.labels.find((entry) => entry.name !== sourceDefault)?.name || state.labels[0]?.name || '';
    fillMergeSelect(mergeSourceSelect, sourceDefault);
    fillMergeSelect(mergeTargetSelect, targetDefault);
  }

  function fillMergeSelect(select, selectedValue) {
    if (!select) return;
    select.innerHTML = '';
    state.labels.forEach((entry) => {
      const option = document.createElement('option');
      option.value = entry.name;
      option.textContent = `${entry.name} (${entry.count})`;
      option.selected = entry.name === selectedValue;
      select.appendChild(option);
    });
  }

  function ensureMergeSelections() {
    if (!mergeSourceSelect || !mergeTargetSelect) return;
    const sourceValue = mergeSourceSelect.value;
    let fallback = '';
    Array.from(mergeTargetSelect.options).forEach((option) => {
      option.disabled = option.value === sourceValue;
      if (!option.disabled && !fallback) {
        fallback = option.value;
      }
    });
    if (!mergeTargetSelect.value || mergeTargetSelect.value === sourceValue) {
      mergeTargetSelect.value = fallback;
    }
    const isValid = Boolean(sourceValue && mergeTargetSelect.value && sourceValue !== mergeTargetSelect.value);
    if (mergeConfirmBtn) {
      mergeConfirmBtn.disabled = !isValid;
    }
  }

  function submitLabelMerge() {
    if (!mergeSourceSelect || !mergeTargetSelect || !mergeConfirmBtn) return;
    const source = mergeSourceSelect.value;
    const target = mergeTargetSelect.value;
    if (!source || !target || source === target) {
      setMergeError('Pick two different labels to merge.');
      ensureMergeSelections();
      return;
    }
    mergeConfirmBtn.disabled = true;
    setMergeError('');
    fetch('/api/labels/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_label: source, target_label: target }),
    })
      .then(checkResponse)
      .then((payload) => {
        closeMergeDialog();
        if (Array.isArray(payload.labels)) {
          state.labels = payload.labels;
        }
        const mergedSource = payload.source_label || source;
        const mergedTarget = payload.target_label || target;
        if (state.activeLabel === mergedSource) {
          state.activeLabel = mergedTarget;
        }
        renderLabelOptions();
        updateSummary();
        if (state.mode === 'verify' && state.activeLabel) {
          startVerify();
        } else if (state.activeLabel) {
          refreshAudit(true);
        } else {
          updateLabelSummary();
        }
      })
      .catch((error) => {
        mergeConfirmBtn.disabled = false;
        setMergeError(error.message || 'Failed to merge labels.');
      });
  }

  function setMergeError(message) {
    if (!mergeErrorEl) return;
    if (!message) {
      mergeErrorEl.textContent = '';
      mergeErrorEl.classList.add('is-hidden');
    } else {
      mergeErrorEl.textContent = message;
      mergeErrorEl.classList.remove('is-hidden');
    }
  }

  function updateMergeButtonState() {
    if (!mergeOpenBtn) return;
    mergeOpenBtn.disabled = state.labels.length < 2;
  }

  function isMergeDialogVisible() {
    return Boolean(mergeDialog && !mergeDialog.classList.contains('is-hidden'));
  }

  // Photo tagging helpers

  function ensurePhotoGridLoaded(forceRefresh = false) {
    if (forceRefresh) {
      refreshPhotoGrid(true);
      return;
    }
    if (!state.photo.items.length && !state.photo.loading) {
      refreshPhotoGrid(true);
    }
  }

  function refreshPhotoGrid(showLoading = false) {
    teardownPhotoOverlayObserver();
    state.photo.gridScrollTop = 0;
    state.photo.selectedIndex = -1;
    state.photo.heroMeta = null;
    state.photo.faces = [];
    state.photo.allFaces = [];
    state.photo.activeFaceId = '';
    state.photo.heroImageLoaded = false;
    state.photo.emptyMessage = '';
    state.photo.manualBoxes = [];
    state.photo.transforms = { front: { rotate: 0 }, back: { rotate: 0 } };
    state.photo.transformLoaded = false;
    state.photo.drawMode = false;
    state.photo.drawing = false;
    state.photo.drawStart = null;
    state.photo.drawBox = null;
    state.photo.drawBoxEl = null;
    state.photo.lockZoom = false;
    setStoredPreference(PHOTO_ZOOM_LOCK_STORAGE_KEY, 'false');
    state.photo.navLocked = false;
    state.photo.cursor = 0;
    state.photo.nextCursor = null;
    state.photo.hasMore = false;
    state.photo.totalPhotos = 0;
    state.photo.items = [];
    state.photo.error = '';
    state.photo.loading = false;
    showPhotoGrid(true);
    renderPhotoHeroPlaceholder();
    renderPhotoGrid();
    setPhotoStatus(showLoading ? 'Loading photos…' : '');
    loadPhotoGrid({ reset: true });
  }

  function renderPhotoHeroPlaceholder() {
    state.photo.heroFrontUrl = '';
    state.photo.heroBackUrl = '';
    state.photo.heroHasBack = false;
    state.photo.viewingBack = false;
    state.photo.transforms = { front: { rotate: 0 }, back: { rotate: 0 } };
    state.photo.transformLoaded = false;
    state.photo.manualBoxes = [];
    state.photo.drawMode = false;
    state.photo.drawing = false;
    state.photo.drawStart = null;
    state.photo.drawBox = null;
    state.photo.drawBoxEl = null;
    state.photo.heroImageLoaded = false;
    if (photoHeroTitle) {
      photoHeroTitle.textContent = 'Photo';
    }
    if (photoHeroSubtitle) {
      photoHeroSubtitle.textContent = '';
    }
    if (photoHeroImg) {
      photoHeroImg.removeAttribute('src');
    }
    if (photoRedetectBtn) {
      photoRedetectBtn.disabled = true;
    }
    if (photoHeroOverlay) {
      photoHeroOverlay.innerHTML = '';
      photoHeroOverlay.classList.toggle('is-hidden', !state.photo.showOverlays);
    }
    if (photoFaceList) {
      photoFaceList.innerHTML = '<p class="empty">Select a photo to begin.</p>';
    }
    updatePhotoPriorityToggle('normal');
    updatePhotoBackToggle();
    updatePhotoOverlayToggle();
    updatePhotoRotateControls();
    updatePhotoDrawToggle();
    applyPhotoZoom();
    updatePhotoNav();
  }

  function loadPhotoGrid(options = {}) {
    if (!photoGridView) return;
    const reset = Boolean(options.reset);
    if (state.photo.gridController) {
      state.photo.gridController.abort();
      state.photo.gridController = null;
    }
    const cursor =
      reset || state.photo.nextCursor === null || typeof state.photo.nextCursor === 'undefined'
        ? 0
        : Number(state.photo.nextCursor) || 0;
    state.photo.cursor = cursor;
    const params = new URLSearchParams({
      limit: String(PHOTO_GRID_PAGE_SIZE),
      cursor: String(cursor),
      min_confidence: state.photo.minConfidence.toFixed(2),
    });
    if (state.photo.priorityFilter && state.photo.priorityFilter !== 'all') {
      params.set('priority', state.photo.priorityFilter);
    }
    const controller = new AbortController();
    state.photo.gridController = controller;
    state.photo.loading = true;
    if (!state.photo.items.length) {
      setPhotoStatus('Loading photos…');
    }
    fetch(`/api/photos?${params.toString()}`, { signal: controller.signal })
      .then(checkResponse)
      .then((payload) => {
        if (controller.signal.aborted) return;
        handlePhotoGridPayload(payload, { reset, cursor });
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        state.photo.error = error.message || 'Failed to load photos.';
        setPhotoStatus(state.photo.error, 'error');
      })
      .finally(() => {
        if (controller.signal.aborted) return;
        if (state.photo.gridController === controller) {
          state.photo.gridController = null;
        }
        state.photo.loading = false;
        updatePhotoGridSummary();
        updateLoadMoreState();
      });
  }

  function handlePhotoGridPayload(payload, { reset, cursor }) {
    state.photo.error = '';
    if (typeof payload?.cursor === 'number') {
      state.photo.cursor = payload.cursor;
    } else if (typeof cursor === 'number') {
      state.photo.cursor = cursor;
    }
    const photos = Array.isArray(payload?.photos) ? payload.photos : [];
    if (reset) {
      state.photo.items = photos.slice();
    } else {
      state.photo.items = state.photo.items.concat(photos);
    }
    state.photo.totalPhotos = typeof payload?.total_photos === 'number' ? payload.total_photos : state.photo.items.length;
    state.photo.hasMore = Boolean(payload?.has_more);
    state.photo.nextCursor =
      typeof payload?.next_cursor === 'number' ? payload.next_cursor : state.photo.hasMore ? state.photo.items.length : null;
    if (payload?.priority_filter) {
      state.photo.priorityFilter = payload.priority_filter;
      if (photoPriorityFilter && photoPriorityFilter.value !== state.photo.priorityFilter) {
        photoPriorityFilter.value = state.photo.priorityFilter;
      }
    }
    sortPhotoItems();
    syncPhotoSelection();
    renderPhotoGrid();
    updatePhotoNav();
    if (!state.photo.items.length) {
      setPhotoStatus('No photos match your filters.', 'info');
    } else if (!state.photo.loading) {
      setPhotoStatus('');
    }
  }

  function sortPhotoItems() {
    state.photo.items.sort((a, b) => {
      const priorityDiff =
        (PHOTO_PRIORITY_ORDER[a?.priority || 'normal'] ?? 1) -
        (PHOTO_PRIORITY_ORDER[b?.priority || 'normal'] ?? 1);
      if (priorityDiff !== 0) return priorityDiff;
      const unlabeledDiff = (b?.unlabeled_count || 0) - (a?.unlabeled_count || 0);
      if (unlabeledDiff !== 0) return unlabeledDiff;
      const confidenceDiff = (b?.max_confidence || 0) - (a?.max_confidence || 0);
      if (confidenceDiff !== 0) return confidenceDiff;
      return (a?.bucket_prefix || '').localeCompare(b?.bucket_prefix || '');
    });
  }

  function syncPhotoSelection() {
    if (!state.photo.items.length) {
      state.photo.selectedIndex = -1;
      return;
    }
    const activePrefix = state.photo.heroMeta?.bucket_prefix;
    if (!activePrefix) return;
    const index = state.photo.items.findIndex((photo) => photo?.bucket_prefix === activePrefix);
    if (index >= 0) {
      state.photo.selectedIndex = index;
      state.photo.heroMeta = state.photo.items[index];
    }
  }

  function setPhotoStatus(message = '', level = 'info') {
    if (!photoStatusEl) return;
    photoStatusEl.textContent = message || '';
    photoStatusEl.classList.toggle('is-error', Boolean(message) && level === 'error');
    photoStatusEl.classList.toggle('is-success', Boolean(message) && level === 'success');
  }

  function renderPhotoGrid() {
    if (!photoGridView) return;
    const previousScroll = photoGridView.scrollTop;
    photoGridView.innerHTML = '';
    if (!state.photo.items.length) {
      const message = state.photo.error || (state.photo.loading ? 'Loading photos…' : 'No photos match your filters.');
      const empty = document.createElement('p');
      empty.className = 'empty';
      empty.textContent = message;
      photoGridView.appendChild(empty);
    } else {
      const fragment = document.createDocumentFragment();
      state.photo.items.forEach((photo, index) => {
        fragment.appendChild(buildPhotoCard(photo, index));
      });
      photoGridView.appendChild(fragment);
    }
    updatePhotoGridSummary();
    updateLoadMoreState();
    if (photoGridFooter) {
      photoGridFooter.classList.toggle('is-hidden', !state.photo.items.length && !state.photo.hasMore);
    }
    requestAnimationFrame(() => {
      photoGridView.scrollTop = previousScroll;
    });
  }

  function buildPhotoCard(photo, index) {
    const card = document.createElement('div');
    card.className = 'photo-card';
    card.dataset.index = String(index);
    card.setAttribute('role', 'button');
    card.setAttribute('tabindex', '0');
    const openHero = () => openPhotoHero(index);
    card.addEventListener('click', () => openHero());
    card.addEventListener('keydown', (event) => {
      if ((event.key === 'Enter' || event.key === ' ') && !event.altKey && !event.metaKey && !event.ctrlKey) {
        event.preventDefault();
        openHero();
      }
    });

    const imageWrap = document.createElement('div');
    imageWrap.className = 'photo-card__image';
    const img = document.createElement('img');
    img.alt = photo.bucket_prefix || 'Photo';
    img.loading = 'lazy';
    if (photo.image_url) {
      img.src = photo.image_url;
    }
    imageWrap.appendChild(img);
    card.appendChild(imageWrap);

    const meta = document.createElement('div');
    meta.className = 'photo-card__meta';
    const title = document.createElement('p');
    title.className = 'photo-card__title';
    title.textContent = photo.bucket_prefix || 'Photo';
    meta.appendChild(title);
    const badges = document.createElement('div');
    badges.className = 'photo-card__badges';
    const unlabeledBadge = document.createElement('span');
    unlabeledBadge.className = 'photo-card__badge photo-card__badge--alert';
    unlabeledBadge.textContent = `${photo.unlabeled_count || 0} unlabeled`;
    badges.appendChild(unlabeledBadge);
    const confBadge = document.createElement('span');
    confBadge.className = 'photo-card__badge';
    confBadge.textContent = `Max conf ${(photo.max_confidence || 0).toFixed(2)}`;
    badges.appendChild(confBadge);
    if (photo.priority && photo.priority !== 'normal') {
      const priorityBadge = document.createElement('span');
      priorityBadge.className = 'photo-card__badge';
      priorityBadge.textContent = `${photo.priority} priority`;
      badges.appendChild(priorityBadge);
    }
    meta.appendChild(badges);
    const priorityControls = document.createElement('div');
    priorityControls.className = 'photo-card__priority';
    ['high', 'normal', 'low'].forEach((level) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'photo-card__priority-btn';
      if ((photo.priority || 'normal') === level) {
        button.classList.add('is-active');
      }
      button.textContent = level === 'high' ? 'High' : level === 'low' ? 'Low' : 'Normal';
      button.disabled = state.photo.prioritySaving;
      button.addEventListener('click', (event) => {
        event.preventDefault();
        event.stopPropagation();
        setPhotoPriorityForBucket(photo.bucket_prefix, level);
      });
      priorityControls.appendChild(button);
    });
    meta.appendChild(priorityControls);
    card.appendChild(meta);
    return card;
  }

  function updatePhotoGridSummary() {
    if (!photoGridSummary) return;
    if (!state.photo.items.length && !state.photo.loading) {
      photoGridSummary.textContent = 'No photos to display.';
      return;
    }
    const parts = [];
    parts.push(`Showing ${state.photo.items.length} of ${state.photo.totalPhotos || state.photo.items.length}`);
    parts.push(`Min conf ${state.photo.minConfidence.toFixed(2)}`);
    if (state.photo.minFaceArea > 0) {
      parts.push(`Min area ${state.photo.minFaceArea.toFixed(3)}`);
    }
    if (state.photo.hideLabeled) {
      parts.push('Hide labeled');
    }
    if (state.photo.priorityFilter && state.photo.priorityFilter !== 'all') {
      parts.push(`Priority: ${state.photo.priorityFilter}`);
    }
    photoGridSummary.textContent = parts.join(' • ');
  }

  function updateLoadMoreState() {
    if (!photoLoadMoreBtn) return;
    photoLoadMoreBtn.disabled = state.photo.loading || !state.photo.hasMore;
    photoLoadMoreBtn.textContent = state.photo.loading ? 'Loading…' : 'Load More';
  }

  function showPhotoGrid(showGrid = true) {
    state.photo.viewingGrid = Boolean(showGrid);
    if (!photoGridView || !photoHeroView) return;
    if (state.photo.viewingGrid) {
      state.photo.navLocked = false;
      if (photoHeroView && !photoHeroView.classList.contains('is-hidden')) {
        state.photo.gridScrollTop = photoGridView.scrollTop || state.photo.gridScrollTop;
      }
      photoGridView.classList.remove('is-hidden');
      photoHeroView.classList.add('is-hidden');
      photoGridToggle?.classList.add('is-hidden');
      if (pageScrollEl) {
        pageScrollEl.scrollTop = state.photo.pageScrollTop || 0;
      }
      requestAnimationFrame(() => {
        photoGridView.scrollTop = state.photo.gridScrollTop || 0;
      });
    } else {
      state.photo.gridScrollTop = photoGridView.scrollTop || 0;
      if (pageScrollEl) {
        state.photo.pageScrollTop = pageScrollEl.scrollTop || 0;
        pageScrollEl.scrollTop = 0;
      }
      if (photoHeroView) {
        photoHeroView.scrollTop = 0;
      }
      if (photoFaceList) {
        photoFaceList.scrollTop = 0;
      }
      photoGridView.classList.add('is-hidden');
      photoHeroView.classList.remove('is-hidden');
      photoGridToggle?.classList.remove('is-hidden');
    }
    if (photoRedetectBtn) {
      photoRedetectBtn.disabled = state.photo.viewingGrid || !state.photo.heroMeta;
    }
    updatePhotoNav();
  }

  function stepPhotoSelection(delta) {
    const direction = Number(delta) || 0;
    if (!direction) return;
    if (state.photo.navLocked) return;
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

  function openPhotoHero(index) {
    const safeIndex = Number.isInteger(index) ? index : state.photo.selectedIndex;
    if (safeIndex < 0 || safeIndex >= state.photo.items.length) {
      return;
    }
    const photo = state.photo.items[safeIndex];
    if (!photo) return;
    state.photo.selectedIndex = safeIndex;
    state.photo.heroMeta = photo;
    state.photo.viewingBack = false;
    state.photo.emptyMessage = '';
    state.photo.faces = [];
    state.photo.allFaces = [];
    state.photo.activeFaceId = '';
    state.photo.manualBoxes = [];
    state.photo.transforms = { front: { rotate: 0 }, back: { rotate: 0 } };
    state.photo.transformLoaded = false;
    state.photo.drawMode = false;
    state.photo.drawing = false;
    state.photo.drawStart = null;
    state.photo.drawBox = null;
    state.photo.drawBoxEl = null;
    resetPhotoZoomState({ unlock: true });
    state.photo.navToken += 1;
    state.photo.navLocked = true;
    const navToken = state.photo.navToken;
    hydratePhotoHeroFromMeta(photo);
    updatePhotoHeroHeader(photo);
    updatePhotoBackToggle();
    updatePhotoOverlayToggle();
    updatePhotoDrawToggle();
    if (photoRedetectBtn) {
      photoRedetectBtn.disabled = false;
    }
    loadPhotoTransform(photo.bucket_prefix);
    loadManualBoxes(photo.bucket_prefix);
    showPhotoGrid(false);
    renderPhotoFaceList(true);
    setPhotoStatus('Loading photo…');
    loadPhotoFaces(photo, navToken);
    updatePhotoNav();
  }

  function hydratePhotoHeroFromMeta(photo) {
    state.photo.heroFrontUrl = photo?.image_url || '';
    state.photo.heroBackUrl = photo?.back_url || '';
    state.photo.heroHasBack = Boolean(photo?.has_back && state.photo.heroBackUrl);
    state.photo.viewingBack = false;
    if (state.photo.heroFrontUrl) {
      renderPhotoHeroImage(state.photo.heroFrontUrl);
    } else if (photoHeroImg) {
      photoHeroImg.removeAttribute('src');
    }
  }

  function updatePhotoHeroHeader(photo) {
    if (photoHeroTitle) {
      photoHeroTitle.textContent = photo?.bucket_prefix || 'Photo';
    }
    if (photoHeroSubtitle) {
      const parts = [];
      if (photo?.bucket_source) {
        parts.push(photo.bucket_source);
      }
      if (typeof photo?.unlabeled_count === 'number') {
        parts.push(`${photo.unlabeled_count} unlabeled`);
      }
      photoHeroSubtitle.textContent = parts.join(' • ');
    }
    updatePhotoPriorityToggle(photo?.priority || 'normal');
  }

  function loadPhotoTransform(bucketPrefix) {
    if (!bucketPrefix) return Promise.resolve(null);
    return fetch(`/api/photo/transform?bucket_prefix=${encodeURIComponent(bucketPrefix)}`)
      .then(checkResponse)
      .then((payload) => {
        const front = payload?.front || { rotate: 0 };
        const back = payload?.back || { rotate: 0 };
        state.photo.transforms = {
          front: { rotate: normalizeRotation(front.rotate) },
          back: { rotate: normalizeRotation(back.rotate) },
        };
        state.photo.transformLoaded = true;
        updatePhotoRotateControls();
        applyPhotoZoom();
        return state.photo.transforms;
      })
      .catch(() => null);
  }

  function getPhotoRotation(side) {
    if (!side) return 0;
    const entry = state.photo.transforms?.[side];
    return normalizeRotation(entry?.rotate ?? 0);
  }

  function setPhotoRotation(side, value) {
    if (!state.photo.heroMeta) return Promise.resolve(false);
    const normalized = normalizeRotation(value);
    state.photo.transforms = state.photo.transforms || { front: { rotate: 0 }, back: { rotate: 0 } };
    state.photo.transforms[side] = { rotate: normalized };
    applyPhotoZoom();
    updatePhotoRotateControls();
    return fetch('/api/photo/transform', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: state.photo.heroMeta.bucket_prefix,
        side,
        rotate: normalized,
      }),
    })
      .then(checkResponse)
      .then((payload) => {
        const next = normalizeRotation(payload?.rotate ?? normalized);
        state.photo.transforms[side] = { rotate: next };
        applyPhotoZoom();
        updatePhotoRotateControls();
        return true;
      })
      .catch((error) => {
        setPhotoStatus(error.message || 'Failed to save rotation.', 'error');
        return false;
      });
  }

  function updatePhotoRotateControls() {
    if (!photoBackRotate) return;
    const show = state.photo.viewingBack && state.photo.heroHasBack;
    photoBackRotate.classList.toggle('is-hidden', !show);
    photoBackRotate.querySelectorAll('button[data-photo-rotate]').forEach((button) => {
      const action = button.dataset.photoRotate;
      if (action === 'reset') {
        button.disabled = !show || getPhotoRotation('back') === 0;
      } else {
        button.disabled = !show;
      }
    });
  }

  function loadManualBoxes(bucketPrefix) {
    if (!bucketPrefix) return Promise.resolve(null);
    return fetch(`/api/photo/manual_boxes?bucket_prefix=${encodeURIComponent(bucketPrefix)}&side=front`)
      .then(checkResponse)
      .then((payload) => {
        const boxes = Array.isArray(payload?.boxes) ? payload.boxes : [];
        state.photo.manualBoxes = hydrateManualBoxes(boxes);
        applyPhotoFaceFilters();
        renderPhotoFaceList();
        renderPhotoOverlay();
        return state.photo.manualBoxes;
      })
      .catch(() => {
        state.photo.manualBoxes = [];
        applyPhotoFaceFilters();
        renderPhotoFaceList();
        renderPhotoOverlay();
        return null;
      });
  }

  function hydrateManualBoxes(boxes) {
    if (!Array.isArray(boxes)) return [];
    return boxes.map((box, index) => ({
      face_id: `${MANUAL_FACE_PREFIX}${box.id}`,
      manual: true,
      manualBoxId: box.id,
      variant: 'manual',
      confidence: 1,
      bbox: box.bbox,
      state: { label: box.label || '' },
      manualIndex: index + 1,
    }));
  }

  function createManualBox(bbox) {
    if (!state.photo.heroMeta) return Promise.resolve(null);
    return fetch('/api/photo/manual_box', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: state.photo.heroMeta.bucket_prefix,
        side: 'front',
        bbox,
      }),
    })
      .then(checkResponse)
      .then((payload) => payload?.box || null)
      .catch((error) => {
        setPhotoStatus(error.message || 'Failed to save manual box.', 'error');
        return null;
      });
  }

  function updateManualBoxLabel(faceId, label) {
    if (!state.photo.heroMeta) return Promise.resolve(false);
    const manualId = getManualBoxId(faceId);
    if (!manualId) return Promise.resolve(false);
    return fetch('/api/photo/manual_box', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: state.photo.heroMeta.bucket_prefix,
        box_id: manualId,
        label,
      }),
    })
      .then(checkResponse)
      .then((payload) => {
        const updated = payload?.box;
        if (updated) {
          const entry = state.photo.manualBoxes.find((box) => box.manualBoxId === manualId);
          if (entry) {
            entry.state = entry.state || {};
            entry.state.label = updated.label || '';
          }
          renderPhotoFaceList();
          renderPhotoOverlay();
        }
        return true;
      })
      .catch((error) => {
        setPhotoStatus(error.message || 'Failed to label manual box.', 'error');
        return false;
      });
  }

  function loadPhotoFaces(photo, navToken = null) {
    if (!photo?.bucket_prefix) {
      setPhotoStatus('Missing bucket prefix for photo.', 'error');
      releasePhotoNavLock(navToken);
      return;
    }
    loadPhotoTransform(photo.bucket_prefix);
    loadManualBoxes(photo.bucket_prefix);
    if (state.photo.heroController) {
      state.photo.heroController.abort();
      state.photo.heroController = null;
    }
    const controller = new AbortController();
    state.photo.heroController = controller;
    state.photo.facesLoading = true;
    if (photoRedetectBtn) {
      photoRedetectBtn.disabled = true;
    }
    state.photo.emptyMessage = '';
    if (photoFaceList) {
      photoFaceList.innerHTML = '<p class="empty">Loading faces…</p>';
    }
    fetch(
      `/api/photo/${encodeURIComponent(photo.bucket_prefix)}/faces?variant=${encodeURIComponent(PHOTO_DEFAULT_VARIANT)}`,
      { signal: controller.signal }
    )
      .then(checkResponse)
      .then((payload) => {
        if (controller.signal.aborted) return;
        const faces = Array.isArray(payload?.faces) ? payload.faces : [];
        state.photo.allFaces = faces;
        applyPhotoFaceFilters();
        state.photo.heroFrontUrl = payload?.image_url || state.photo.heroFrontUrl || photo.image_url || '';
        state.photo.heroBackUrl = payload?.back_url || state.photo.heroBackUrl || photo.back_url || '';
        state.photo.heroHasBack = Boolean(
          (payload?.has_back && (payload?.back_url || photo.back_url)) || state.photo.heroBackUrl
        );
        if (state.photo.heroMeta) {
          state.photo.heroMeta.back_url = state.photo.heroBackUrl;
          state.photo.heroMeta.has_back = state.photo.heroHasBack;
        }
        state.photo.viewingBack = false;
        updatePhotoBackToggle();
        updatePhotoOverlayToggle();
        renderPhotoFaceList();
        return renderPhotoHeroImage(state.photo.heroFrontUrl);
      })
      .then(() => {
        if (state.photo.faces.length) {
          setPhotoStatus('');
        }
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        state.photo.faces = [];
        state.photo.allFaces = [];
        state.photo.activeFaceId = '';
        state.photo.heroHasBack = Boolean(state.photo.heroBackUrl);
        state.photo.viewingBack = false;
        updatePhotoBackToggle();
        updatePhotoOverlayToggle();
        if (isEmptyPhotoFacesError(error)) {
          updatePhotoEmptyMessage(0);
        } else {
          state.photo.emptyMessage = 'Faces unavailable for this photo.';
          setPhotoStatus(error.message || 'Failed to load photo faces.', 'error');
        }
        renderPhotoFaceList();
        if (state.photo.heroFrontUrl) {
          renderPhotoHeroImage(state.photo.heroFrontUrl);
        }
      })
      .finally(() => {
        if (state.photo.heroController === controller) {
          state.photo.heroController = null;
        }
        state.photo.facesLoading = false;
        if (photoRedetectBtn) {
          photoRedetectBtn.disabled = false;
        }
        releasePhotoNavLock(navToken);
      });
  }

  function renderPhotoHeroImage(imageUrl) {
    state.photo.heroImageLoaded = false;
    if (!photoHeroImg || !imageUrl) {
      if (photoHeroImg) {
        photoHeroImg.removeAttribute('src');
      }
      teardownPhotoOverlayObserver();
      if (photoHeroOverlay) {
        photoHeroOverlay.innerHTML = '';
        photoHeroOverlay.classList.toggle('is-hidden', true);
      }
      setPhotoStatus('Photo image missing.', 'error');
      updatePhotoBackToggle();
      updatePhotoOverlayToggle();
      return Promise.resolve();
    }
    state.photo.heroImageToken += 1;
    const token = state.photo.heroImageToken;
    teardownPhotoOverlayObserver();
    state.photo.heroImageLoaded = false;
    photoHeroOverlay.innerHTML = '';
    photoHeroImg.src = imageUrl;
    const decodePromise =
      typeof photoHeroImg.decode === 'function'
        ? photoHeroImg.decode()
        : new Promise((resolve, reject) => {
            photoHeroImg.addEventListener('load', resolve, { once: true });
            photoHeroImg.addEventListener('error', reject, { once: true });
          });
    return decodePromise
      .then(() => {
        if (token !== state.photo.heroImageToken) return;
        state.photo.heroImageLoaded = true;
        applyPhotoZoom();
        renderPhotoOverlay();
        installPhotoOverlayObserver();
        if (!state.photo.viewingGrid && pageScrollEl) {
          pageScrollEl.scrollTop = 0;
        }
      })
      .catch(() => {
        if (token !== state.photo.heroImageToken) return;
        setPhotoStatus('Failed to load photo image.', 'error');
      });
  }

  function installPhotoOverlayObserver() {
    if (typeof ResizeObserver === 'undefined' || !photoHeroImage) {
      return;
    }
    const observer = new ResizeObserver(() => {
      renderPhotoOverlay();
    });
    observer.observe(photoHeroImage);
    state.photo.overlayCleanup = () => observer.disconnect();
  }

  function teardownPhotoOverlayObserver() {
    if (typeof state.photo.overlayCleanup === 'function') {
      state.photo.overlayCleanup();
    }
    state.photo.overlayCleanup = null;
  }

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
    if (state.photo.drawMode && state.photo.drawBox) {
      ensurePhotoDrawBox();
      if (state.photo.drawBoxEl) {
        positionBoundingBox(photoHeroImage, photoHeroImg, state.photo.drawBoxEl, state.photo.drawBox);
      }
    }
  }

  function renderPhotoFaceList(initial = false) {
    if (!photoFaceList) return;
    photoFaceList.innerHTML = '';
    const faces = state.photo.faces || [];
    if (!faces.length) {
      const empty = document.createElement('p');
      empty.className = 'empty';
      if (initial) {
        empty.textContent = 'Loading faces…';
      } else {
        const banner = buildPhotoEmptyBanner();
        if (banner) {
          photoFaceList.appendChild(banner);
        }
        empty.textContent = 'No faces for this photo.';
      }
      photoFaceList.appendChild(empty);
      updatePhotoPriorityToggle(state.photo.heroMeta?.priority || 'normal');
      return;
    }
    const fragment = document.createDocumentFragment();
    faces.forEach((face) => {
      const item = document.createElement('article');
      item.className = 'photo-face-item';
      item.dataset.faceId = face.face_id || '';
      if (face.manual) {
        item.classList.add('photo-face-item--manual');
      }
      if (face.face_id === state.photo.activeFaceId) {
        item.classList.add('is-active');
      }
      const meta = document.createElement('div');
      meta.className = 'photo-face-item__meta';
      if (face.manual) {
        const label = face.manualIndex ? `Manual ${face.manualIndex}` : 'Manual';
        meta.innerHTML = `<span>${label}</span><span>Custom box</span>`;
      } else {
        meta.innerHTML = `<span>${(face.variant || '').toUpperCase()}</span><span>Conf ${(
          face.confidence || 0
        ).toFixed(2)}</span>`;
      }
      item.appendChild(meta);
      const label = document.createElement('div');
      label.className = 'photo-face-item__label';
      if (face?.state?.label) {
        label.textContent = `Labeled as ${face.state.label}`;
      } else if (face.manual) {
        label.textContent = 'Manual region';
      } else {
        label.textContent = 'Unlabeled';
      }
      item.appendChild(label);
      const actions = document.createElement('div');
      actions.className = 'photo-face-item__actions';
      const button = document.createElement('button');
      button.type = 'button';
      button.dataset.faceAction = 'assign';
      button.dataset.faceId = face.face_id || '';
      if (!state.activeLabel) {
        button.textContent = 'Select a person to assign';
        button.disabled = true;
      } else if (face?.state?.label === state.activeLabel) {
        button.textContent = `Already ${state.activeLabel}`;
        button.disabled = true;
      } else {
        button.textContent = `Assign to ${state.activeLabel}`;
      }
      actions.appendChild(button);
      item.appendChild(actions);
      fragment.appendChild(item);
    });
    photoFaceList.appendChild(fragment);
    scrollActiveFaceIntoView();
    renderPhotoOverlay();
  }

  function handlePhotoOverlayClick(event) {
    if (state.photo.suppressOverlayClick) {
      state.photo.suppressOverlayClick = false;
      return;
    }
    if (state.photo.drawMode || state.photo.drawing) {
      return;
    }
    const target = event.target.closest('.candidate-face-box');
    if (!target?.dataset.faceId) return;
    selectPhotoFace(target.dataset.faceId);
  }

  function handlePhotoFaceListClick(event) {
    const emptyAction = event.target.closest('button[data-photo-empty-action]');
    if (emptyAction?.dataset.photoEmptyAction) {
      event.preventDefault();
      handlePhotoEmptyAction(emptyAction.dataset.photoEmptyAction);
      return;
    }
    const actionButton = event.target.closest('button[data-face-action]');
    if (actionButton?.dataset.faceAction === 'assign' && actionButton.dataset.faceId) {
      event.preventDefault();
      assignFaceToActiveLabel(actionButton.dataset.faceId);
      return;
    }
    const row = event.target.closest('.photo-face-item');
    if (row?.dataset.faceId) {
      selectPhotoFace(row.dataset.faceId);
    }
  }

  function selectPhotoFace(faceId) {
    if (!faceId || faceId === state.photo.activeFaceId) return;
    state.photo.activeFaceId = faceId;
    renderPhotoFaceList();
    maybeFocusLabelFilter(true);
  }

  function scrollActiveFaceIntoView() {
    if (!photoFaceList || !state.photo.activeFaceId) return;
    const active = photoFaceList.querySelector(`.photo-face-item[data-face-id="${state.photo.activeFaceId}"]`);
    if (!active) return;
    const parentRect = photoFaceList.getBoundingClientRect();
    const activeRect = active.getBoundingClientRect();
    if (activeRect.top < parentRect.top || activeRect.bottom > parentRect.bottom) {
      active.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  function assignFaceToActiveLabel(faceId) {
    if (!faceId) return;
    if (!state.activeLabel) {
      setPhotoStatus('Select a person on the left to assign faces.', 'error');
      return;
    }
    const face = state.photo.faces.find((entry) => entry.face_id === faceId);
    if (!face) return;
    if (face?.state?.label === state.activeLabel) {
      setPhotoStatus(`Already labeled as ${state.activeLabel}.`);
      return;
    }
    if (face.manual) {
      setPhotoStatus(`Assigning manual region to ${state.activeLabel}…`);
      updateManualBoxLabel(faceId, state.activeLabel).then((updated) => {
        if (updated) {
          setPhotoStatus(`Assigned to ${state.activeLabel}.`, 'success');
          updatePhotoFaceState(faceId, state.activeLabel);
        }
      });
      return;
    }
    setPhotoStatus(`Assigning to ${state.activeLabel}…`);
    fetch('/api/queue/accept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ face_id: faceId, label: state.activeLabel }),
    })
      .then(checkResponse)
      .then(() => refreshLabelsFromServer())
      .then(() => {
        updatePhotoFaceState(faceId, state.activeLabel);
        setPhotoStatus(`Assigned to ${state.activeLabel}.`, 'success');
      })
      .catch((error) => {
        setPhotoStatus(error.message || 'Failed to assign face.', 'error');
      });
  }

  function buildPhotoEmptyBanner() {
    if (!state.photo.heroMeta) return null;
    const banner = document.createElement('div');
    banner.className = 'photo-empty-banner';
    const message = document.createElement('p');
    message.className = 'photo-empty-banner__text';
    message.textContent = state.photo.emptyMessage || 'No faces detected in this photo (with current filters).';
    banner.appendChild(message);

    const actions = document.createElement('div');
    actions.className = 'photo-empty-banner__actions';
    actions.appendChild(buildPhotoEmptyAction('Lower threshold', 'lower-threshold'));
    actions.appendChild(buildPhotoEmptyAction('Re-detect faces', 'redetect'));
    actions.appendChild(buildPhotoEmptyAction('Mark Low priority', 'priority-low'));
    actions.appendChild(buildPhotoEmptyAction('Copy bucket id', 'copy-bucket'));
    actions.appendChild(buildPhotoEmptyAction('Open in Bucket Review', 'open-review'));
    banner.appendChild(actions);

    const meta = document.createElement('div');
    meta.className = 'photo-empty-banner__meta';
    const label = document.createElement('span');
    label.textContent = 'Bucket:';
    const code = document.createElement('code');
    code.textContent = state.photo.heroMeta.bucket_prefix || '';
    meta.appendChild(label);
    meta.appendChild(code);
    banner.appendChild(meta);
    return banner;
  }

  function buildPhotoEmptyAction(label, action) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'photo-empty-banner__button';
    button.dataset.photoEmptyAction = action;
    button.textContent = label;
    return button;
  }

  function handlePhotoEmptyAction(action) {
    if (!state.photo.heroMeta) return;
    if (action === 'lower-threshold') {
      if (setPhotoMinConfidence(PHOTO_EMPTY_LOWER_THRESHOLD, { refreshGrid: false })) {
        applyPhotoFaceFilters();
        renderPhotoFaceList();
        renderPhotoOverlay();
        updatePhotoGridSummary();
      }
      return;
    }
    if (action === 'redetect') {
      handlePhotoRedetect();
      return;
    }
    if (action === 'priority-low') {
      const promise = setPhotoPriority('low');
      if (promise && typeof promise.then === 'function') {
        promise.then((updated) => {
          if (updated) {
            stepPhotoSelection(1);
          }
        });
      }
      return;
    }
    if (action === 'copy-bucket') {
      copyPhotoBucketPrefix();
      return;
    }
    if (action === 'open-review') {
      openBucketReview();
    }
  }

  function copyPhotoBucketPrefix() {
    const prefix = state.photo.heroMeta?.bucket_prefix || '';
    if (!prefix) return;
    if (navigator.clipboard?.writeText) {
      navigator.clipboard
        .writeText(prefix)
        .then(() => setPhotoStatus('Bucket id copied.', 'success'))
        .catch(() => fallbackCopyText(prefix));
      return;
    }
    fallbackCopyText(prefix);
  }

  function fallbackCopyText(text) {
    const helper = document.createElement('textarea');
    helper.value = text;
    helper.setAttribute('readonly', 'true');
    helper.style.position = 'absolute';
    helper.style.left = '-9999px';
    document.body.appendChild(helper);
    helper.select();
    try {
      document.execCommand('copy');
      setPhotoStatus('Bucket id copied.', 'success');
    } catch (error) {
      setPhotoStatus('Failed to copy bucket id.', 'error');
    } finally {
      helper.remove();
    }
  }

  function openBucketReview() {
    window.open('/views/review/index.html', '_blank', 'noopener');
  }

  function updatePhotoFaceState(faceId, label) {
    updatePhotoFaceStateEntry(state.photo.faces, faceId, label);
    updatePhotoFaceStateEntry(state.photo.allFaces, faceId, label);
    updatePhotoFaceStateEntry(state.photo.manualBoxes, faceId, label);
    applyPhotoFaceFilters();
    const photo = state.photo.items[state.photo.selectedIndex];
    if (photo && photo.unlabeled_count > 0 && !isManualFace(faceId)) {
      photo.unlabeled_count = Math.max(0, photo.unlabeled_count - 1);
      updatePhotoHeroHeader(photo);
      renderPhotoGrid();
    }
    renderPhotoFaceList();
  }

  function updatePhotoNav() {
    if (!photoCounterEl) return;
    if (state.photo.viewingGrid || state.photo.selectedIndex === -1) {
      photoCounterEl.textContent = `${state.photo.items.length} photos`;
    } else {
      photoCounterEl.textContent = `${state.photo.selectedIndex + 1} / ${state.photo.items.length}`;
    }
    const disablePrev = state.photo.viewingGrid || state.photo.selectedIndex <= 0 || state.photo.navLocked;
    const disableNext =
      state.photo.viewingGrid ||
      !state.photo.items.length ||
      state.photo.selectedIndex >= state.photo.items.length - 1 ||
      state.photo.navLocked;
    if (photoPrevBtn) photoPrevBtn.disabled = disablePrev;
    if (photoNextBtn) photoNextBtn.disabled = disableNext && !state.photo.hasMore;
  }

  function handlePhotoPriorityFilterChange() {
    const value = photoPriorityFilter?.value || 'all';
    if (state.photo.priorityFilter === value) return;
    state.photo.priorityFilter = value;
    refreshPhotoGrid(true);
  }

  function handlePhotoMinConfidenceChange(rawValue) {
    if (!setPhotoMinConfidence(rawValue, { refreshGrid: true })) return;
    applyPhotoFaceFilters();
    renderPhotoFaceList();
    renderPhotoOverlay();
    updatePhotoGridSummary();
  }

  function setPhotoMinConfidence(rawValue, { refreshGrid = false } = {}) {
    const parsed = clamp(parseFloat(rawValue));
    const normalized = Number.isFinite(parsed) ? parsed : PHOTO_DEFAULT_MIN_CONFIDENCE;
    if (photoMinConfidenceInput) {
      photoMinConfidenceInput.value = normalized.toFixed(2);
    }
    if (Math.abs(state.photo.minConfidence - normalized) < 0.0001) return false;
    state.photo.minConfidence = normalized;
    if (refreshGrid) {
      refreshPhotoGrid(true);
    }
    return true;
  }

  function handlePhotoMinFaceAreaChange(rawValue) {
    if (!setPhotoMinFaceArea(rawValue)) return;
    applyPhotoFaceFilters();
    renderPhotoFaceList();
    renderPhotoOverlay();
  }

  function setPhotoMinFaceArea(rawValue) {
    const parsed = clamp(parseFloat(rawValue));
    const normalized = Number.isFinite(parsed) ? parsed : PHOTO_DEFAULT_MIN_FACE_AREA;
    if (photoMinFaceAreaInput) {
      photoMinFaceAreaInput.value = normalized.toFixed(3);
    }
    if (Math.abs(state.photo.minFaceArea - normalized) < 0.0001) return false;
    state.photo.minFaceArea = normalized;
    return true;
  }

  function handlePhotoHideLabeledToggle() {
    state.photo.hideLabeled = Boolean(photoHideLabeledInput?.checked);
    applyPhotoFaceFilters();
    renderPhotoFaceList();
    renderPhotoOverlay();
  }

  function updatePhotoPriorityToggle(priority) {
    if (!photoPriorityToggle) return;
    const normalized = PHOTO_PRIORITY_ORDER.hasOwnProperty(priority) ? priority : 'normal';
    const disableButtons = !state.photo.heroMeta || state.photo.prioritySaving;
    photoPriorityToggle.querySelectorAll('button[data-photo-priority]').forEach((button) => {
      const isActive = button.dataset.photoPriority === normalized;
      button.classList.toggle('is-active', isActive);
      button.disabled = disableButtons;
    });
  }

  function setPhotoPriority(priority) {
    if (!state.photo.heroMeta) return Promise.resolve(false);
    return setPhotoPriorityForBucket(state.photo.heroMeta.bucket_prefix, priority);
  }

  function setPhotoPriorityForBucket(bucketPrefix, priority) {
    if (!bucketPrefix || state.photo.prioritySaving) return Promise.resolve(false);
    const normalized = (priority || '').toLowerCase();
    if (!PHOTO_PRIORITY_ORDER.hasOwnProperty(normalized)) return Promise.resolve(false);
    const current = state.photo.items.find((entry) => entry.bucket_prefix === bucketPrefix);
    if (current && current.priority === normalized) return Promise.resolve(false);
    state.photo.prioritySaving = true;
    updatePhotoPriorityToggle(state.photo.heroMeta?.priority || 'normal');
    renderPhotoGrid();
    return fetch('/api/photo/priority', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: bucketPrefix,
        priority: normalized,
      }),
    })
      .then(checkResponse)
      .then((payload) => {
        const value = payload?.priority || normalized;
        if (current) {
          current.priority = value;
        }
        if (state.photo.heroMeta && state.photo.heroMeta.bucket_prefix === bucketPrefix) {
          state.photo.heroMeta.priority = value;
          updatePhotoHeroHeader(state.photo.heroMeta);
        }
        if (state.photo.priorityFilter !== 'all' && state.photo.priorityFilter !== value) {
          setPhotoStatus('Photo moved out of current filter.', 'info');
          refreshPhotoGrid(true);
        } else {
          sortPhotoItems();
          syncPhotoSelection();
          renderPhotoGrid();
          updatePhotoNav();
        }
        return true;
      })
      .catch((error) => {
        setPhotoStatus(error.message || 'Failed to update priority.', 'error');
        return false;
      })
      .finally(() => {
        state.photo.prioritySaving = false;
        updatePhotoPriorityToggle(state.photo.heroMeta?.priority || 'normal');
        renderPhotoGrid();
      });
  }

  function applyPhotoFaceFilters() {
    const faces = Array.isArray(state.photo.allFaces) ? state.photo.allFaces : [];
    const manual = Array.isArray(state.photo.manualBoxes) ? state.photo.manualBoxes : [];
    const combined = faces.concat(manual);
    const minConfidence = state.photo.minConfidence;
    const minArea = state.photo.minFaceArea;
    const hideLabeled = state.photo.hideLabeled;
    const filtered = combined.filter((face) => {
      if (face?.manual) {
        if (hideLabeled && face?.state?.label) return false;
        return true;
      }
      if ((face?.confidence || 0) < minConfidence) return false;
      if (minArea > 0 && getFaceArea(face) < minArea) return false;
      if (hideLabeled && face?.state?.label) return false;
      return true;
    });
    state.photo.faces = filtered;
    const firstUnlabeled = filtered.find((face) => !(face?.state?.label));
    state.photo.activeFaceId = firstUnlabeled?.face_id || filtered[0]?.face_id || '';
    updatePhotoEmptyMessage(faces.length);
  }

  function updatePhotoEmptyMessage(totalFaces) {
    if (state.photo.faces.length) {
      state.photo.emptyMessage = '';
      return;
    }
    state.photo.emptyMessage = getPhotoEmptyMessage(totalFaces);
  }

  function releasePhotoNavLock(token) {
    if (token === null || typeof token === 'undefined') return;
    if (token !== state.photo.navToken) return;
    state.photo.navLocked = false;
  }

  function getPhotoEmptyMessage(totalFaces) {
    if (totalFaces > 0) {
      return 'No faces detected in this photo (with current filters).';
    }
    return 'No faces detected in this photo.';
  }

  function getFaceArea(face) {
    const bbox = face?.bbox || face?.bbox_xywh || {};
    const width = Number(bbox.width ?? bbox.w ?? 0);
    const height = Number(bbox.height ?? bbox.h ?? 0);
    if (!Number.isFinite(width) || !Number.isFinite(height)) return 0;
    return Math.max(0, width) * Math.max(0, height);
  }

  function updatePhotoFaceStateEntry(list, faceId, label) {
    if (!Array.isArray(list)) return;
    const face = list.find((entry) => entry.face_id === faceId);
    if (face) {
      face.state = face.state || {};
      face.state.label = label;
    }
  }

  function isEmptyPhotoFacesError(error) {
    const message = (error && error.message ? String(error.message) : '').toLowerCase();
    return message.includes('no faces') || message.includes('not found for that bucket');
  }

  function handlePhotoBackToggle() {
    if (!state.photo.heroHasBack || !photoBackToggle) return;
    state.photo.viewingBack = !state.photo.viewingBack;
    state.photo.drawMode = false;
    state.photo.drawing = false;
    clearPhotoDrawBox();
    resetPhotoZoomState({ unlock: true });
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

  function updatePhotoBackToggle() {
    if (!photoBackToggle) return;
    const show = Boolean(state.photo.heroHasBack);
    photoBackToggle.classList.toggle('is-hidden', !show);
    if (!show) {
      photoBackToggle.textContent = 'Show Back';
      photoBackToggle.setAttribute('aria-pressed', 'false');
      photoBackToggle.disabled = true;
      updatePhotoRotateControls();
      updatePhotoDrawToggle();
      return;
    }
    photoBackToggle.disabled = false;
    photoBackToggle.textContent = state.photo.viewingBack ? 'Show Front' : 'Show Back';
    photoBackToggle.setAttribute('aria-pressed', state.photo.viewingBack ? 'true' : 'false');
    updatePhotoRotateControls();
    updatePhotoDrawToggle();
  }

  function handlePhotoOverlayToggle() {
    if (state.photo.viewingBack) return;
    state.photo.showOverlays = !state.photo.showOverlays;
    setStoredPreference(PHOTO_OVERLAY_STORAGE_KEY, state.photo.showOverlays ? 'true' : 'false');
    if (!state.photo.showOverlays && state.photo.drawMode) {
      state.photo.drawMode = false;
      clearPhotoDrawBox();
      updatePhotoDrawToggle();
    }
    updatePhotoOverlayToggle();
    renderPhotoOverlay();
  }

  function handlePhotoRotateClick(event) {
    const button = event.target.closest('button[data-photo-rotate]');
    if (!button || !state.photo.heroHasBack) return;
    const action = button.dataset.photoRotate;
    if (action === 'reset') {
      setPhotoRotation('back', 0);
      return;
    }
    if (action === 'ccw') {
      setPhotoRotation('back', getPhotoRotation('back') - 90);
      return;
    }
    if (action === 'cw') {
      setPhotoRotation('back', getPhotoRotation('back') + 90);
    }
  }

  function handlePhotoRedetect() {
    if (!state.photo.heroMeta || state.photo.facesLoading) return;
    const bucketPrefix = state.photo.heroMeta.bucket_prefix;
    if (!bucketPrefix) return;
    setPhotoStatus('Re-detecting faces…');
    if (photoRedetectBtn) {
      photoRedetectBtn.disabled = true;
    }
    fetch('/api/photo/redetect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: bucketPrefix,
        variant: PHOTO_DEFAULT_VARIANT,
        min_confidence: state.photo.minConfidence,
        merge_iou: 0.6,
      }),
    })
      .then(checkResponse)
      .then((payload) => {
        const faces = Array.isArray(payload?.faces) ? payload.faces : [];
        state.photo.allFaces = faces;
        applyPhotoFaceFilters();
        renderPhotoFaceList();
        renderPhotoOverlay();
        loadManualBoxes(bucketPrefix);
        const added = typeof payload?.added === 'number' ? payload.added : 0;
        setPhotoStatus(added ? `Added ${added} face(s).` : 'No new faces found.', 'info');
      })
      .catch((error) => {
        setPhotoStatus(error.message || 'Failed to re-detect faces.', 'error');
      })
      .finally(() => {
        if (photoRedetectBtn) {
          photoRedetectBtn.disabled = false;
        }
      });
  }

  function updatePhotoOverlayToggle() {
    if (!photoOverlayToggle) return;
    const viewingBack = state.photo.viewingBack && state.photo.heroHasBack;
    photoOverlayToggle.disabled = viewingBack;
    photoOverlayToggle.classList.toggle('is-disabled', viewingBack);
    if (viewingBack) {
      photoOverlayToggle.textContent = 'Boxes disabled on back';
      return;
    }
    photoOverlayToggle.textContent = state.photo.showOverlays ? 'Hide Boxes' : 'Show Boxes';
    photoOverlayToggle.setAttribute('aria-pressed', state.photo.showOverlays ? 'true' : 'false');
  }

  function updatePhotoDrawToggle() {
    if (!photoDrawToggle || !photoHeroImage) return;
    const enabled = Boolean(state.photo.heroMeta) && !state.photo.viewingBack;
    if (!enabled && state.photo.drawMode) {
      state.photo.drawMode = false;
      state.photo.drawing = false;
      clearPhotoDrawBox();
    }
    photoDrawToggle.disabled = !enabled;
    photoDrawToggle.classList.toggle('is-active', state.photo.drawMode && enabled);
    photoHeroImage.classList.toggle('is-drawing', state.photo.drawMode && enabled);
  }

  function handlePhotoZoomSliderChange(rawValue) {
    const parsed = clampZoom(parseFloat(rawValue));
    applyPhotoZoomDelta(parsed, { anchor: 'center' });
    renderPhotoOverlay();
  }

  function handlePhotoZoomAdjust(delta) {
    if (!delta) return;
    const nextZoom = clampZoom(state.photo.zoom + delta);
    applyPhotoZoomDelta(nextZoom, { anchor: 'center' });
    renderPhotoOverlay();
  }

  function resetPhotoZoom() {
    resetPhotoZoomState();
    applyPhotoZoom();
    renderPhotoOverlay();
  }

  function resetPhotoZoomState({ unlock = false } = {}) {
    if (unlock) {
      state.photo.lockZoom = false;
      setStoredPreference(PHOTO_ZOOM_LOCK_STORAGE_KEY, 'false');
      updatePhotoZoomLockUI();
    }
    state.photo.zoom = 1;
    state.photo.panX = 0;
    state.photo.panY = 0;
    setStoredPreference(PHOTO_ZOOM_STORAGE_KEY, state.photo.zoom);
  }

  function handlePhotoWheelZoom(event) {
    if (!photoHeroImage) return;
    if (state.photo.viewingGrid) return;
    if (state.photo.drawMode) return;
    event.preventDefault();
    const rect = photoHeroImage.getBoundingClientRect();
    const anchor = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
    const delta = event.deltaY < 0 ? 0.1 : -0.1;
    const nextZoom = clampZoom(state.photo.zoom + delta);
    applyPhotoZoomDelta(nextZoom, { anchor });
    renderPhotoOverlay();
  }

  function applyPhotoZoomDelta(nextZoom, { anchor = null } = {}) {
    const zoom = clampZoom(nextZoom);
    if (Math.abs(zoom - state.photo.zoom) < 0.001) {
      updatePhotoZoomUI();
      return;
    }
    const rect = photoHeroImage?.getBoundingClientRect();
    const anchorX =
      anchor === 'center' || !anchor ? (rect ? rect.width / 2 : 0) : anchor.x ?? (rect ? rect.width / 2 : 0);
    const anchorY =
      anchor === 'center' || !anchor ? (rect ? rect.height / 2 : 0) : anchor.y ?? (rect ? rect.height / 2 : 0);
    const currentZoom = state.photo.zoom || 1;
    const panX = state.photo.panX || 0;
    const panY = state.photo.panY || 0;
    const contentX = (anchorX - panX) / currentZoom;
    const contentY = (anchorY - panY) / currentZoom;
    state.photo.panX = anchorX - contentX * zoom;
    state.photo.panY = anchorY - contentY * zoom;
    state.photo.zoom = zoom;
    setStoredPreference(PHOTO_ZOOM_STORAGE_KEY, zoom);
    applyPhotoZoom();
  }

  function applyPhotoZoom() {
    if (!photoZoomCanvas) return;
    const zoom = clampZoom(state.photo.zoom);
    const panX = state.photo.panX || 0;
    const panY = state.photo.panY || 0;
    const rotation = state.photo.viewingBack ? getPhotoRotation('back') : getPhotoRotation('front');
    const fitScale = getPhotoRotationFitScale(rotation);
    const scaleSegment = fitScale !== 1 ? ` scale(${fitScale})` : '';
    const rotateSegment = rotation ? ` rotate(${rotation}deg)` : '';
    photoZoomCanvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})${scaleSegment}${rotateSegment}`;
    updatePhotoZoomUI();
  }

  function getPhotoRotationFitScale(rotation) {
    if (!rotation || rotation % 180 === 0) {
      return 1;
    }
    if (!photoHeroImage || !photoHeroImg) {
      return 1;
    }
    const imgWidth = photoHeroImg.naturalWidth || photoHeroImg.width || 1;
    const imgHeight = photoHeroImg.naturalHeight || photoHeroImg.height || 1;
    const wrapperWidth = photoHeroImage.clientWidth || imgWidth;
    const wrapperHeight = photoHeroImage.clientHeight || imgHeight;
    const scaleX = wrapperWidth / imgHeight;
    const scaleY = wrapperHeight / imgWidth;
    const fit = Math.min(scaleX, scaleY);
    if (!Number.isFinite(fit) || fit <= 0) {
      return 1;
    }
    return fit;
  }

  let isPhotoPanning = false;
  let photoPanPointerId = null;
  let photoPanLastX = 0;
  let photoPanLastY = 0;
  let photoPanMoved = false;

  function handlePhotoPanStart(event) {
    if (event.button !== 0) return;
    if (state.photo.drawMode) {
      handlePhotoDrawStart(event);
      return;
    }
    if (event.target.closest('.candidate-face-box')) return;
    if (!photoHeroImage) return;
    isPhotoPanning = true;
    photoPanMoved = false;
    photoPanPointerId = event.pointerId;
    photoPanLastX = event.clientX;
    photoPanLastY = event.clientY;
    photoHeroImage.classList.add('is-panning');
    if (photoHeroImage.setPointerCapture) {
      photoHeroImage.setPointerCapture(event.pointerId);
    }
  }

  function handlePhotoPanMove(event) {
    if (state.photo.drawing) {
      handlePhotoDrawMove(event);
      return;
    }
    if (!isPhotoPanning || event.pointerId !== photoPanPointerId) return;
    const dx = event.clientX - photoPanLastX;
    const dy = event.clientY - photoPanLastY;
    if (Math.abs(dx) > 1 || Math.abs(dy) > 1) {
      photoPanMoved = true;
    }
    photoPanLastX = event.clientX;
    photoPanLastY = event.clientY;
    state.photo.panX += dx;
    state.photo.panY += dy;
    applyPhotoZoom();
  }

  function handlePhotoPanEnd(event) {
    if (state.photo.drawing) {
      handlePhotoDrawEnd(event);
      return;
    }
    if (!isPhotoPanning || event.pointerId !== photoPanPointerId) return;
    isPhotoPanning = false;
    photoPanPointerId = null;
    if (photoHeroImage) {
      photoHeroImage.classList.remove('is-panning');
    }
    if (photoPanMoved) {
      state.photo.suppressOverlayClick = true;
    }
  }

  function updatePhotoZoomUI() {
    if (photoZoomSlider) {
      photoZoomSlider.value = clampZoom(state.photo.zoom).toFixed(2);
    }
    if (photoZoomValue) {
      photoZoomValue.textContent = `${clampZoom(state.photo.zoom).toFixed(1)}×`;
    }
    updatePhotoZoomLockUI();
  }

  function togglePhotoZoomLock() {
    state.photo.lockZoom = !state.photo.lockZoom;
    setStoredPreference(PHOTO_ZOOM_LOCK_STORAGE_KEY, state.photo.lockZoom ? 'true' : 'false');
    updatePhotoZoomLockUI();
  }

  function updatePhotoZoomLockUI() {
    if (!photoZoomLockBtn) return;
    photoZoomLockBtn.classList.toggle('is-active', state.photo.lockZoom);
    photoZoomLockBtn.setAttribute('aria-pressed', state.photo.lockZoom ? 'true' : 'false');
  }

  function togglePhotoDrawMode() {
    if (!state.photo.heroMeta || state.photo.viewingBack) return;
    state.photo.drawMode = !state.photo.drawMode;
    if (state.photo.drawMode) {
      state.photo.showOverlays = true;
      setStoredPreference(PHOTO_OVERLAY_STORAGE_KEY, 'true');
      updatePhotoOverlayToggle();
    } else {
      clearPhotoDrawBox();
    }
    updatePhotoDrawToggle();
  }

  function handlePhotoDrawStart(event) {
    if (event.button !== 0) return;
    if (!photoHeroImage || !photoHeroImg) return;
    if (!state.photo.heroImageLoaded) return;
    if (state.photo.viewingBack) return;
    event.preventDefault();
    const start = getPhotoPointerRaw(event);
    if (!start) return;
    state.photo.drawing = true;
    state.photo.drawStart = start;
    state.photo.drawBox = null;
    ensurePhotoDrawBox();
    if (photoHeroImage.setPointerCapture) {
      photoHeroImage.setPointerCapture(event.pointerId);
    }
    updatePhotoDrawBox(event);
  }

  function handlePhotoDrawMove(event) {
    if (!state.photo.drawing) return;
    updatePhotoDrawBox(event);
  }

  function handlePhotoDrawEnd(event) {
    if (!state.photo.drawing) return;
    state.photo.drawing = false;
    if (photoHeroImage?.releasePointerCapture && event.pointerId) {
      photoHeroImage.releasePointerCapture(event.pointerId);
    }
    const bbox = state.photo.drawBox;
    if (bbox && bbox.width >= PHOTO_DRAW_MIN_SIZE && bbox.height >= PHOTO_DRAW_MIN_SIZE) {
      createManualBox(bbox).then((box) => {
        if (box) {
          loadManualBoxes(state.photo.heroMeta?.bucket_prefix || '');
          setPhotoStatus('Manual box added.', 'success');
        }
      });
    }
    clearPhotoDrawBox();
    state.photo.drawMode = false;
    updatePhotoDrawToggle();
  }

  function getPhotoPointerRaw(event) {
    if (!photoHeroImage) return null;
    const rect = photoHeroImage.getBoundingClientRect();
    const localX = event.clientX - rect.left;
    const localY = event.clientY - rect.top;
    const zoom = clampZoom(state.photo.zoom || 1);
    const panX = state.photo.panX || 0;
    const panY = state.photo.panY || 0;
    return {
      x: (localX - panX) / zoom,
      y: (localY - panY) / zoom,
    };
  }

  function updatePhotoDrawBox(event) {
    if (!state.photo.drawStart || !photoHeroImage || !photoHeroImg) return;
    const current = getPhotoPointerRaw(event);
    if (!current) return;
    const bbox = computeDrawBBox(state.photo.drawStart, current);
    state.photo.drawBox = bbox;
    if (bbox && state.photo.drawBoxEl) {
      positionBoundingBox(photoHeroImage, photoHeroImg, state.photo.drawBoxEl, bbox);
    }
  }

  function computeDrawBBox(start, current) {
    const metrics = getRenderedImageRect(photoHeroImage, photoHeroImg);
    const startX = (start.x - metrics.offsetX) / metrics.drawWidth;
    const startY = (start.y - metrics.offsetY) / metrics.drawHeight;
    const endX = (current.x - metrics.offsetX) / metrics.drawWidth;
    const endY = (current.y - metrics.offsetY) / metrics.drawHeight;
    const left = clamp01(Math.min(startX, endX));
    const top = clamp01(Math.min(startY, endY));
    const right = clamp01(Math.max(startX, endX));
    const bottom = clamp01(Math.max(startY, endY));
    const width = Math.max(0, right - left);
    const height = Math.max(0, bottom - top);
    if (width <= 0 || height <= 0) return null;
    return { left, top, width, height };
  }

  function ensurePhotoDrawBox() {
    if (!photoHeroOverlay || state.photo.drawBoxEl) return;
    const box = document.createElement('div');
    box.className = 'candidate-face-box candidate-face-box--manual candidate-face-box--active';
    box.dataset.faceId = 'draw-preview';
    photoHeroOverlay.appendChild(box);
    state.photo.drawBoxEl = box;
  }

  function clearPhotoDrawBox() {
    if (state.photo.drawBoxEl && state.photo.drawBoxEl.parentNode) {
      state.photo.drawBoxEl.parentNode.removeChild(state.photo.drawBoxEl);
    }
    state.photo.drawBoxEl = null;
    state.photo.drawBox = null;
    state.photo.drawStart = null;
  }

  function handlePhotoModeHotkeys(event, key) {
    if (event.repeat && (key === 'arrowright' || key === 'arrowleft')) {
      return true;
    }
    if (key === 'arrowright') {
      event.preventDefault();
      stepPhotoSelection(1);
      return true;
    }
    if (key === 'arrowleft') {
      event.preventDefault();
      stepPhotoSelection(-1);
      return true;
    }
    if (key === 'g' && !state.photo.viewingGrid) {
      showPhotoGrid(true);
      return true;
    }
    if (key === 'l' && state.photo.hasMore && !state.photo.loading) {
      loadPhotoGrid();
      return true;
    }
    return false;
  }

  function drawFaceInset(img, bbox) {
    if (!insetCanvas || !insetCtx || !state.candidate) return;
    const width = insetCanvas.width || 400;
    const height = insetCanvas.height || 400;
    insetCanvas.width = width;
    insetCanvas.height = height;
    insetCtx.clearRect(0, 0, width, height);
    if (!img.complete) {
      img.addEventListener(
        'load',
        () => drawFaceInset(img, bbox),
        { once: true }
      );
      return;
    }
    const sx = (bbox.left || 0) * img.naturalWidth;
    const sy = (bbox.top || 0) * img.naturalHeight;
    const sw = (bbox.width || 0) * img.naturalWidth;
    const sh = (bbox.height || 0) * img.naturalHeight;
    if (!sw || !sh) return;
    const pad = 0.25;
    const paddedX = Math.max(sx - sw * pad, 0);
    const paddedY = Math.max(sy - sh * pad, 0);
    const paddedW = Math.min(sw * (1 + pad * 2), img.naturalWidth - paddedX);
    const paddedH = Math.min(sh * (1 + pad * 2), img.naturalHeight - paddedY);
    insetCtx.drawImage(img, paddedX, paddedY, paddedW, paddedH, 0, 0, width, height);
  }

  function positionBoundingBox(wrapper, img, box, bbox, cachedMetrics) {
    if (!box || !bbox) return;
    const metrics = cachedMetrics || getRenderedImageRect(wrapper, img);
    const left = metrics.offsetX + bbox.left * metrics.drawWidth;
    const top = metrics.offsetY + bbox.top * metrics.drawHeight;
    const width = bbox.width * metrics.drawWidth;
    const height = bbox.height * metrics.drawHeight;
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
    box.style.width = `${width}px`;
    box.style.height = `${height}px`;
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

  function normalizeBoundingBox(raw) {
    if (!raw) return null;
    const left = typeof raw.left === 'number' ? raw.left : raw.x;
    const top = typeof raw.top === 'number' ? raw.top : raw.y;
    const width = typeof raw.width === 'number' ? raw.width : raw.w;
    const height = typeof raw.height === 'number' ? raw.height : raw.h;
    if ([left, top, width, height].some((val) => typeof val !== 'number')) {
      return null;
    }
    return { left, top, width, height };
  }

  function normalizeRotation(value) {
    if (!Number.isFinite(value)) return 0;
    let next = Math.round(value) % 360;
    if (next < 0) next += 360;
    return Math.round(next / 90) * 90 % 360;
  }

  function clamp01(value) {
    if (!Number.isFinite(value)) return 0;
    return Math.min(1, Math.max(0, value));
  }

  function getManualBoxId(faceId) {
    if (!faceId || typeof faceId !== 'string') return '';
    return faceId.startsWith(MANUAL_FACE_PREFIX) ? faceId.slice(MANUAL_FACE_PREFIX.length) : '';
  }

  function isManualFace(faceId) {
    if (!faceId || typeof faceId !== 'string') return false;
    return faceId.startsWith(MANUAL_FACE_PREFIX);
  }

  function updateSimilarityDisplay() {
    if (similarityValue) similarityValue.textContent = state.similarity.toFixed(2);
  }

  function handleHotkeys(event) {
    const key = event.key ? event.key.toLowerCase() : '';
    if (!key) return;
    if (isMergeDialogVisible()) {
      if (key === 'escape') {
        closeMergeDialog();
      }
      return;
    }
    const activeTag = document.activeElement?.tagName;
    if (activeTag === 'INPUT' || activeTag === 'TEXTAREA' || activeTag === 'SELECT') {
      return;
    }
    if (state.uiMode === 'photo') {
      if (handlePhotoModeHotkeys(event, key)) {
        return;
      }
      if (key === 'escape') {
        showPhotoGrid(true);
        return;
      }
    }
    switch (key) {
      case 't':
      case 'enter':
        if (state.mode === 'seed') {
          submitSeedLabel();
        } else if (state.view === 'single') {
          handleDecision('accept');
        }
        break;
      case 'f':
        if (state.mode === 'verify' && state.view === 'single') {
          handleDecision('reject');
        }
        break;
      case 's':
        if (state.view === 'single') {
          skipBtn?.click();
        }
        break;
      case 'c':
        refreshBtn?.click();
        break;
      case 'r':
        refreshBtn?.click();
        break;
      case 'n':
        newPersonBtn?.click();
        break;
      case 'b':
        if (state.view === 'batch') {
          commitBatchDecisions();
        } else {
          handleIgnore();
        }
        break;
      case 'g':
        setView('batch');
        break;
      case 'u':
        handleUndo();
        break;
      case 'arrowright':
        if (state.view === 'single') {
          event.preventDefault();
          handleSkip();
        }
        break;
      case 'arrowleft':
        if (state.view === 'single') {
          event.preventDefault();
          navigateHistoryBackward();
        }
        break;
    }
  }

  function renderCandidateFacesOverlay(layer, wrapper, img, faces, activeFaceId) {
    if (!layer || !wrapper || !img || !faces || !faces.length) {
      if (layer) layer.innerHTML = '';
      return;
    }
    layer.innerHTML = '';
    const metrics = getRenderedImageRect(wrapper, img);
    faces.forEach((face) => {
      const bbox = normalizeBoundingBox(face?.bbox || face?.bbox_xywh);
      if (!bbox) {
        return;
      }
      const box = document.createElement('div');
      box.className = 'candidate-face-box';
      if (face.face_id) {
        box.dataset.faceId = face.face_id;
      }
      if (face.manual) {
        box.classList.add('candidate-face-box--manual');
      }
      if (face.face_id === activeFaceId) {
        box.classList.add('candidate-face-box--active');
      } else if (face?.state?.label) {
        box.classList.add('candidate-face-box--labeled');
      } else {
        box.classList.add('candidate-face-box--unlabeled');
      }
      layer.appendChild(box);
      requestAnimationFrame(() => positionBoundingBox(wrapper, img, box, bbox, metrics));
    });
  }

  function navigateHistoryBackward() {
    if (!hasHistorySupport() || !state.history?.past.length) return false;
    const previous = state.history.past.pop();
    if (state.candidate) {
      const clone = snapshotCandidate(state.candidate);
      if (clone) {
        state.history.future.push(clone);
      }
    }
    state.candidate = previous;
    renderCandidate();
    disableDecisionButtons(false);
    return true;
  }

  function navigateHistoryForward() {
    if (!hasHistorySupport() || !state.history?.future.length) return false;
    const next = state.history.future.pop();
    if (state.candidate) {
      const clone = snapshotCandidate(state.candidate);
      if (clone) {
        state.history.past.push(clone);
        if (state.history.past.length > HISTORY_LIMIT) {
          state.history.past.shift();
        }
      }
    }
    state.candidate = next;
    renderCandidate();
    disableDecisionButtons(false);
    return true;
  }

  function checkResponse(response) {
    const contentType = response.headers.get('content-type') || '';
    const isJSON = contentType.includes('application/json');
    if (!response.ok) {
      if (isJSON) {
        return response.json().then((payload) => {
          const message = payload?.message || payload?.error || response.statusText || 'Request failed';
          throw new Error(message);
        });
      }
      return response.text().then((text) => {
        const cleaned = text ? text.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() : '';
        throw new Error(cleaned || response.statusText || 'Request failed');
      });
    }
    if (isJSON) {
      return response.json();
    }
    return response.text().then((text) => {
      if (!text) return {};
      try {
        return JSON.parse(text);
      } catch (error) {
        return {};
      }
    });
  }

  function getStoredPreference(key, fallback = '') {
    try {
      if (!key || !window?.localStorage) return fallback;
      const value = window.localStorage.getItem(key);
      return value === null || typeof value === 'undefined' ? fallback : value;
    } catch (error) {
      return fallback;
    }
  }

  function setStoredPreference(key, value) {
    try {
      if (!key || !window?.localStorage) return;
      window.localStorage.setItem(key, String(value));
    } catch (error) {
      // ignore
    }
  }

  function clampZoom(value) {
    if (!Number.isFinite(value)) return 1;
    return Math.min(PHOTO_ZOOM_MAX, Math.max(PHOTO_ZOOM_MIN, value));
  }

  function clamp(value) {
    if (Number.isNaN(value)) return 0;
    return Math.min(1, Math.max(0, value));
  }

  function setAppMode(mode) {
    const normalized = mode === 'photo' ? 'photo' : 'person';
    state.uiMode = normalized;
    const isPhoto = normalized === 'photo';
    modePersonBtn?.classList.toggle('is-active', !isPhoto);
    modePhotoBtn?.classList.toggle('is-active', isPhoto);
    personModeSection?.classList.toggle('is-hidden', isPhoto);
    photoModeSection?.classList.toggle('is-hidden', !isPhoto);
    if (isPhoto) {
      ensurePhotoGridLoaded();
      showPhotoGrid(true);
    }
  }

  function maybeFocusLabelFilter(force = false) {
    if (!force) return;
    if (state.uiMode !== 'photo') return;
    if (!state.photo.activeFaceId) return;
    if (!labelFilterInput) return;
    if (document.activeElement === labelFilterInput) return;
    labelFilterInput.focus({ preventScroll: true });
  }
})();
