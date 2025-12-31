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
  const sidebarRefreshBtn = document.getElementById('sidebar-refresh-btn');

  let suppressLabelChange = false;

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
  };

  init();

  function init() {
    updateSummary();
    renderLabelOptions();
    setupControls();
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
    sidebarRefreshBtn?.addEventListener('click', () => refreshLabelsFromServer());
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
    state.mode = 'seed';
    state.activeLabel = '';
    updateLabelSummary();
    renderLabelList();
    setView('single');
    disableDecisionButtons(true);
    toggleSeedControls(true);
    setCandidate(null);
    updateModeText('Label a new person.');
    renderMessage('Loading…');
    fetchSeedCandidate();
  }

  function startVerify() {
    if (!state.activeLabel) {
      renderMessage('Select a label or start a new person.');
      return;
    }
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
    const box = document.createElement('div');
    box.className = 'candidate-image__box';
    candidateImage.appendChild(box);
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

    const bbox = state.candidate.bbox || {};
    const applyBox = () => positionBoundingBox(candidateImage, img, box, bbox);
    if (img.complete) {
      applyBox();
    } else {
      img.addEventListener('load', applyBox, { once: true });
    }
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

  function renderLabelList() {
    if (!labelList) return;
    labelList.innerHTML = '';
    if (!state.labels.length) {
      labelList.innerHTML = '<p class="empty">No labels yet — add someone with “New Person”.</p>';
      return;
    }
    state.labels.forEach((entry) => {
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
    updateLabelSummary();
    renderLabelList();
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

  function positionBoundingBox(wrapper, img, box, bbox) {
    const wrapperRect = wrapper.getBoundingClientRect();
    const imgRect = img.getBoundingClientRect();
    const drawWidth = imgRect.width || wrapperRect.width || 1;
    const drawHeight = imgRect.height || wrapperRect.height || 1;
    const offsetX = imgRect.left - wrapperRect.left;
    const offsetY = imgRect.top - wrapperRect.top;
    const left = offsetX + (bbox.left || 0) * drawWidth;
    const top = offsetY + (bbox.top || 0) * drawHeight;
    const width = (bbox.width || 0) * drawWidth;
    const height = (bbox.height || 0) * drawHeight;
    box.style.left = `${left}px`;
    box.style.top = `${top}px`;
    box.style.width = `${width}px`;
    box.style.height = `${height}px`;
  }

  function updateSimilarityDisplay() {
    if (similarityValue) similarityValue.textContent = state.similarity.toFixed(2);
  }

  function handleHotkeys(event) {
    if (isMergeDialogVisible()) {
      if (event.key.toLowerCase() === 'escape') {
        closeMergeDialog();
      }
      return;
    }
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'SELECT') return;
    switch (event.key.toLowerCase()) {
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
    }
  }

  function checkResponse(response) {
    if (!response.ok) {
      return response.text().then((text) => {
        throw new Error(text || 'Request failed');
      });
    }
    return response.json();
  }

  function clamp(value) {
    if (Number.isNaN(value)) return 0;
    return Math.min(1, Math.max(0, value));
  }
})();
