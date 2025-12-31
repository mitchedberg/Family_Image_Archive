(function () {
  const MIN_ZOOM = 1;
  const MAX_ZOOM = 4;

  const DATA = window.REVIEW_DATA || {};
  const allBuckets = DATA.buckets || [];
  if (allBuckets.length === 0) {
    const summary = document.getElementById('summary');
    if (summary) summary.textContent = 'No buckets to review.';
    return;
  }

  const sources = Array.from(new Set(allBuckets.map((bucket) => normalizeSource(bucket.source)))).sort();
  const storedSources = parseStoredArray('review_sources');
  const initialSelection = storedSources.filter((value) => sources.includes(value));

  const state = {
    buckets: allBuckets,
    visible: allBuckets.slice(),
    index: 0,
    history: [],
    filters: {
      allSources: sources,
      sources: new Set(initialSelection.length ? initialSelection : sources),
    },
    zoom: clampZoom(parseFloat(localStorage.getItem('review_zoom') || '1') || 1),
    pan: parseStoredPan(),
    fullRes: localStorage.getItem('review_fullres') === '1',
    compareMode: localStorage.getItem('review_compare_mode') === 'back' ? 'back' : 'ai',
    variantFilter: parseVariantFilter(localStorage.getItem('review_variant_filter')),
    photoTransforms: Object.create(null),
    photoTransformRequests: new Map(),
  };
  const sessionId = createSessionId();
  let pendingNoteFlag = false;

  const bucketContainer = document.getElementById('bucket-container');
  const summaryEl = document.getElementById('summary');
  const sourceFiltersEl = document.getElementById('source-filters');
  const zoomSlider = document.getElementById('zoom-slider');
  const zoomValue = document.getElementById('zoom-value');
  const zoomReset = document.getElementById('zoom-reset');
  const zoomInBtn = document.getElementById('zoom-in');
  const zoomOutBtn = document.getElementById('zoom-out');
  const fullResToggle = document.getElementById('fullres-toggle');
  const compareToggle = document.getElementById('compare-toggle');
  const variantFiltersEl = document.getElementById('variant-filters');
  const prevBtn = document.getElementById('btn-prev');
  const nextBtn = document.getElementById('btn-next');
  const noteInput = document.getElementById('note-input');
  const noteStatusEl = document.getElementById('note-status');
  const voiceTranscriptList = document.getElementById('voice-transcript-list');
  const ocrReadonlyEl = document.getElementById('ocr-readonly');
  const statusBar = document.getElementById('status-bar');
  const shortcutBar = document.getElementById('shortcut-bar');
  const ocrButton = document.getElementById('ocr-back-button');
  const markDraftButton = document.getElementById('mark-draft-button');
  const markVerifiedButton = document.getElementById('mark-verified-button');
  const noteAddInput = document.getElementById('note-add-input');
  const noteAddButton = document.getElementById('note-add-button');
  const ocrStatusEl = document.getElementById('ocr-status');
  const noteEditToggle = document.getElementById('note-edit-toggle');
  const noteLockIndicator = document.getElementById('note-lock-indicator');
  const filterToggle = document.getElementById('filter-toggle');
  const filterClose = document.getElementById('filter-close');
  const filterPanel = document.getElementById('filter-panel');
  const notesToggle = document.getElementById('notes-toggle');
  const notesToggleSecondary = document.getElementById('notes-toggle-secondary');
  const noteDrawer = document.getElementById('note-drawer');
  const noteDrawerCollapse = document.getElementById('note-drawer-collapse');
  const noteBucketChip = document.getElementById('note-bucket-chip');
  const noteSummaryVoice = document.getElementById('note-summary-voice');
  const noteSummaryOcr = document.getElementById('note-summary-ocr');
  const noteSummaryManual = document.getElementById('note-summary-manual');
  const noteTabs = Array.from(document.querySelectorAll('[data-note-tab]'));
  const notePanels = Array.from(document.querySelectorAll('[data-note-panel]'));
  const copyVoiceButton = document.getElementById('note-copy-voice');
  const copyOcrButton = document.getElementById('note-copy-ocr');
  const helpToggle = document.getElementById('help-toggle');
  const shortcutPanel = document.getElementById('shortcut-panel');
  const shortcutClose = document.getElementById('shortcut-close');
  const stateOverlay = document.getElementById('state-overlay');
  let zoomAnchor = null;
  let noteSaveTimer = null;
  let pendingNoteOptions = {};
  const fullResCache = new Map();
  const stateChangeCallbacks = new Set();
  let lastStateSignature = null;
  let noteEditingUnlocked = false;
  const drawerStates = ['collapsed', 'peek', 'expanded'];
  let drawerStateIndex = 1;
  let shortcutsOpen = false;
  let activeNoteTab = 'voice';

  window.bucketReview = Object.assign(window.bucketReview || {}, {
    getCurrentState,
    onStateChange,
    sessionId,
  });

  window.addEventListener('load', () => {
    window.scrollTo(0, 0);
  });

  applyFilters({
    skipRender: true,
    initialIndex: parseInt(localStorage.getItem('review_index') || '0', 10),
    skipFilterPersistence: true,
    skipFullRes: true,
  });

  setupZoomControls();
  setupSourceFilters();
  setupFullResToggle();
  setupCompareControls();
  setupVariantFilters();
  setupBackRotationControls();
  setupNavButtons();
  setupOcrButton();
  setupStatusButtons();
  setupNoteEditor();
  setupFilterPanel();
  setupShortcutPanel();
  setupNotesDrawer();
  setupNoteTabs();
  setupCopyButtons();
  registerPointerHandlers();
  render();

  document.addEventListener('keydown', (event) => {
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
      return;
    }
    switch (event.key.toLowerCase()) {
      case 'j':
      case 'arrowdown':
        nextBucket();
        break;
      case 'k':
      case 'arrowup':
        prevBucket();
        break;
      case '1':
        applyDecision('prefer_original');
        break;
      case '2':
        applyDecision('prefer_ai');
        break;
      case '3':
        applyDecision('flag_creepy');
        break;
      case 'u':
        undoDecision();
        break;
      case 'g':
        jumpPrompt();
        break;
      case '=':
      case '+':
        nudgeZoom(0.1);
        break;
      case '-':
      case '_':
        nudgeZoom(-0.1);
        break;
      case '0':
        resetZoomState();
        break;
      case 'h':
        toggleFullRes();
        break;
      case 'f':
        document.documentElement.requestFullscreen?.();
        break;
      case 'v':
        markOcrStatus('verified', { advance: true });
        break;
      case 'm':
        queueNoteFlag();
        break;
      case 'n':
        cycleNoteDrawer();
        break;
      case '?':
        toggleShortcutPanel();
        break;
    }
  });

  function queueNoteFlag() {
    pendingNoteFlag = true;
    setStatus('Next image will include a note flag marker.');
    updateStateOverlay(getCurrentState());
  }

  function consumePendingNoteFlag() {
    if (!pendingNoteFlag) {
      return false;
    }
    pendingNoteFlag = false;
    return true;
  }

  bucketContainer.addEventListener('click', (event) => {
    const revealBtn = event.target.closest('button[data-reveal-role]');
    if (revealBtn) {
      event.stopPropagation();
      revealVariant(revealBtn.dataset.revealRole);
      return;
    }
    const duplicateBtn = event.target.closest('button[data-duplicate-target]');
    if (duplicateBtn) {
      event.stopPropagation();
      focusBucketByPrefix(duplicateBtn.dataset.duplicateTarget || '');
      return;
    }
    const row = event.target.closest('.bucket-row');
    if (!row) return;
    const idx = Number(row.dataset.index);
    if (Number.isNaN(idx) || idx === state.index) return;
    state.index = clampIndex(idx);
    render();
  });

  function setupZoomControls() {
    if (!zoomSlider) return;
    zoomSlider.value = state.zoom.toFixed(2);
    updateZoomValue();
    zoomSlider.addEventListener('input', (event) => {
      setZoom(clampZoom(parseFloat(event.target.value)));
    });
    if (zoomInBtn) {
      zoomInBtn.addEventListener('click', () => nudgeZoom(0.1));
    }
    if (zoomOutBtn) {
      zoomOutBtn.addEventListener('click', () => nudgeZoom(-0.1));
    }
    if (zoomReset) {
      zoomReset.addEventListener('click', () => {
        setZoom(1);
        setPan({ x: 0, y: 0 });
      });
    }
  }

  function setupSourceFilters() {
    if (!sourceFiltersEl) return;
    sourceFiltersEl.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-source-chip]');
      if (!button) return;
      const value = button.dataset.sourceChip;
      if (value === '__all__') {
        state.filters.sources = new Set(state.filters.allSources);
      } else if (state.filters.sources.has(value)) {
        state.filters.sources.delete(value);
      } else {
        state.filters.sources.add(value);
      }
      if (!state.filters.sources.size) {
        state.filters.sources = new Set(state.filters.allSources);
      }
      persistSources();
      renderSourceChips();
      applyFilters();
    });
    renderSourceChips();
  }

  function setupFullResToggle() {
    if (!fullResToggle) return;
    fullResToggle.addEventListener('click', () => {
      toggleFullRes();
    });
    updateFullResButton();
  }

  function setupCompareControls() {
    if (!compareToggle) return;
    compareToggle.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-compare]');
      if (!button) return;
      const mode = button.dataset.compare;
      if (mode && mode !== state.compareMode) {
        setCompareMode(mode);
      }
    });
    updateCompareButtons();
  }

  function setupVariantFilters() {
    if (!variantFiltersEl) return;
    variantFiltersEl.addEventListener('click', (event) => {
      const button = event.target.closest('button[data-variant-filter]');
      if (!button) return;
      const value = button.dataset.variantFilter;
      if (!value) return;
      const next = state.variantFilter === value ? null : value;
      setVariantFilter(next);
    });
    updateVariantFilterButtons();
  }

  function setupBackRotationControls() {
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-back-rotate]');
      if (!button) return;
      const action = button.dataset.backRotate;
      if (action === 'ccw') {
        rotateBack(-90);
      } else if (action === 'cw') {
        rotateBack(90);
      } else if (action === 'reset') {
        resetBackRotation();
      }
    });
  }

  function setupNavButtons() {
    if (prevBtn) {
      prevBtn.addEventListener('click', () => prevBucket());
    }
    if (nextBtn) {
      nextBtn.addEventListener('click', () => nextBucket());
    }
  }

  function setupOcrButton() {
    if (!ocrButton) return;
    ocrButton.addEventListener('click', () => {
      runOcrForBucket();
    });
  }

  function setupStatusButtons() {
    if (markDraftButton) {
      markDraftButton.addEventListener('click', () => markOcrStatus('draft'));
    }
    if (markVerifiedButton) {
      markVerifiedButton.addEventListener('click', () => markOcrStatus('verified', { advance: true }));
    }
  }

  function setCompareMode(mode) {
    if (mode !== 'ai' && mode !== 'back') {
      return;
    }
    state.compareMode = mode;
    localStorage.setItem('review_compare_mode', mode);
    updateCompareButtons();
    render();
  }

  function updateCompareButtons() {
    if (!compareToggle) return;
    const buttons = compareToggle.querySelectorAll('button[data-compare]');
    buttons.forEach((button) => {
      const isActive = button.dataset.compare === state.compareMode;
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function setVariantFilter(value) {
    const valid = parseVariantFilter(value);
    if (state.variantFilter === valid) return;
    state.variantFilter = valid;
    persistVariantFilter();
    updateVariantFilterButtons();
    applyFilters();
  }

  function updateVariantFilterButtons() {
    if (!variantFiltersEl) return;
    const buttons = variantFiltersEl.querySelectorAll('button[data-variant-filter]');
    buttons.forEach((button) => {
      const value = button.dataset.variantFilter || '';
      const isActive = value === state.variantFilter;
      button.classList.toggle('active', isActive);
      button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
    });
  }

  function setupNoteEditor() {
    if (!noteInput) return;
    noteInput.addEventListener('input', () => {
      if (noteInput.readOnly) {
        return;
      }
      const bucket = state.visible[state.index];
      if (!bucket) return;
      const voiceBlocks = bucket._voiceBlocks || [];
      bucket.note = rebuildNoteFromManual(noteInput.value, voiceBlocks);
      bucket.prefilledAuto = false;
      bucket.ocr_status = 'draft';
      updateOcrStatusDisplay(bucket);
      updateNoteStatus('Saving…');
      scheduleNoteSave(bucket.bucket_prefix, { ocrStatus: 'draft' });
      renderNoteSummary(bucket);
    });
    noteInput.addEventListener('blur', () => {
      flushNoteSave();
    });
    if (noteEditToggle) {
      noteEditToggle.addEventListener('click', () => {
        noteEditingUnlocked = !noteEditingUnlocked;
        applyNoteLockState();
      });
    }
    if (noteAddButton && noteAddInput) {
      noteAddButton.addEventListener('click', () => {
        addManualNote();
      });
      noteAddInput.addEventListener('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'enter') {
          event.preventDefault();
          addManualNote();
        }
      });
    }
    applyNoteLockState();
  }

  function syncNoteEditor(bucket) {
    if (!noteInput) return;
    if (!bucket) {
      noteInput.value = '';
      noteInput.dataset.bucket = '';
      noteInput.disabled = true;
      noteEditingUnlocked = false;
      applyNoteLockState();
      updateNoteStatus('');
      updateOcrStatusDisplay(null);
      return;
    }
    noteInput.disabled = false;
    noteInput.dataset.bucket = bucket.bucket_prefix;
    const voiceBlocks = getVoiceBlocks(bucket);
    bucket._voiceBlocks = voiceBlocks;
    const manualText = stripVoiceBlocks(bucket.note || '', voiceBlocks);
    noteInput.value = manualText || '';
    if (!bucket.note) {
      updateNoteStatus('');
    }
    updateOcrStatusDisplay(bucket);
    noteEditingUnlocked = false;
    applyNoteLockState();
  }

  function scheduleNoteSave(prefix, options = {}) {
    if (!prefix) return;
    pendingNoteOptions = options || {};
    if (noteSaveTimer) {
      clearTimeout(noteSaveTimer);
    }
    noteSaveTimer = setTimeout(() => {
      noteSaveTimer = null;
      persistNote(prefix, pendingNoteOptions);
      pendingNoteOptions = {};
    }, 500);
  }

  function flushNoteSave() {
    if (noteSaveTimer) {
      clearTimeout(noteSaveTimer);
      noteSaveTimer = null;
    }
    const prefix = noteInput?.dataset.bucket;
    if (prefix) {
      persistNote(prefix, pendingNoteOptions);
      pendingNoteOptions = {};
    }
  }

  function persistNote(prefix, options = {}) {
    const bucket = state.buckets.find((b) => b.bucket_prefix === prefix);
    if (!bucket) return Promise.resolve();
    return saveDecision(bucket, bucket.decision, bucket.note || '', {
      skipRender: true,
      silent: true,
      ocrStatus: options.ocrStatus,
    })
      .then(() => {
        updateNoteStatus(bucket.note ? 'Saved' : '');
      })
      .catch((err) => {
        updateNoteStatus('Failed to save', true);
        setStatus('Failed to save note: ' + err.message, true);
      });
  }

  function updateNoteStatus(message, isError = false) {
    if (!noteStatusEl) return;
    noteStatusEl.textContent = message || '';
    if (isError) {
      noteStatusEl.classList.add('status-bar--error');
    } else {
      noteStatusEl.classList.remove('status-bar--error');
    }
  }

  function addManualNote() {
    if (!noteAddInput || !noteInput) return;
    const text = noteAddInput.value.trim();
    if (!text) {
      setStatus('Enter a note to add.', true);
      return;
    }
    const bucket = state.visible[state.index];
    if (!bucket) return;
    const stamp = new Date().toLocaleString();
    const block = `[${stamp}] ${text}`;
    const current = noteInput.value.trim();
    noteInput.value = current ? `${current}\n\n${block}` : block;
    noteAddInput.value = '';
    const voiceBlocks = bucket._voiceBlocks || [];
    bucket.note = rebuildNoteFromManual(noteInput.value, voiceBlocks);
    bucket.ocr_status = 'draft';
    updateOcrStatusDisplay(bucket);
    updateNoteStatus('Saving…');
    scheduleNoteSave(bucket.bucket_prefix, { ocrStatus: 'draft' });
    setStatus('Note added.');
    renderNoteSummary(bucket);
  }

  function buildAutoNote(bucket) {
    if (!bucket || !bucket.auto_ocr) return '';
    const parts = [];
    if (bucket.auto_ocr.front_text) {
      parts.push(`Front:\n${bucket.auto_ocr.front_text}`);
    }
    if (bucket.auto_ocr.back_text) {
      parts.push(`Back:\n${bucket.auto_ocr.back_text}`);
    }
    return parts.join('\n\n').trim();
  }

  function buildOcrManualBlock(bucket) {
    if (!bucket) return '';
    const parts = [];
    const human = bucket.human_ocr || {};
    if (human.text) {
      parts.push(`Human OCR:\n${human.text}`);
    }
    const auto = buildAutoNote(bucket);
    if (auto) {
      parts.push(`Auto OCR:\n${auto}`);
    }
    return parts.join('\n\n').trim();
  }

  function insertVoiceIntoManual() {
    const bucket = state.visible[state.index];
    if (!bucket) return false;
    const transcripts = Array.isArray(bucket.voice_transcripts) ? bucket.voice_transcripts : [];
    if (!transcripts.length) return false;
    const latest = transcripts[transcripts.length - 1];
    let body = String(latest.note_block || '').trim();
    if (!body && Array.isArray(latest.entries) && latest.entries.length) {
      body = latest.entries.map((entry) => `${entry.image_id || 'image'}: ${entry.text || ''}`).join('\n');
    }
    if (!body) return false;
    const labelParts = ['VOICE'];
    if (latest.speaker) labelParts.push(latest.speaker);
    if (latest.created_at) labelParts.push(latest.created_at);
    return appendManualBlock(bucket, body, labelParts.join(' · '));
  }

  function insertOcrIntoManual() {
    const bucket = state.visible[state.index];
    if (!bucket) return false;
    const text = buildOcrManualBlock(bucket);
    if (!text) return false;
    return appendManualBlock(bucket, text, 'OCR');
  }

  function appendManualBlock(bucket, text, label) {
    if (!bucket || !noteInput || !text) return false;
    if (noteInput.readOnly) {
      noteEditingUnlocked = true;
      applyNoteLockState();
    }
    const cleaned = text.trim();
    if (!cleaned) return false;
    const header = label ? `[${label}]` : '';
    const block = header ? `${header}\n${cleaned}` : cleaned;
    const current = noteInput.value.trim();
    noteInput.value = current ? `${current}\n\n${block}` : block;
    const voiceBlocks = bucket._voiceBlocks || [];
    bucket.note = rebuildNoteFromManual(noteInput.value, voiceBlocks);
    bucket.ocr_status = 'draft';
    updateOcrStatusDisplay(bucket);
    updateNoteStatus('Saving…');
    scheduleNoteSave(bucket.bucket_prefix, { ocrStatus: 'draft' });
    renderNoteSummary(bucket);
    setStatus(`${label || 'Text'} copied to manual notes.`);
    return true;
  }

  function applyNoteLockState() {
    if (!noteInput) return;
    const locked = !noteEditingUnlocked;
    noteInput.readOnly = locked;
    noteInput.classList.toggle('note-input--locked', locked);
    if (noteEditToggle) {
      noteEditToggle.textContent = locked ? 'Unlock Editing' : 'Lock Editing';
      noteEditToggle.classList.toggle('active', !locked);
    }
    if (noteLockIndicator) {
      noteLockIndicator.textContent = locked ? 'Notes locked' : 'Editing enabled';
    }
  }

  function setupFilterPanel() {
    if (!filterToggle || !filterPanel) return;
    const closePanel = () => {
      filterPanel.classList.remove('filter-panel--open');
      filterPanel.setAttribute('aria-hidden', 'true');
      filterToggle.setAttribute('aria-expanded', 'false');
    };
    const openPanel = () => {
      filterPanel.classList.add('filter-panel--open');
      filterPanel.setAttribute('aria-hidden', 'false');
      filterToggle.setAttribute('aria-expanded', 'true');
    };
    filterToggle.addEventListener('click', (event) => {
      event.stopPropagation();
      if (filterPanel.classList.contains('filter-panel--open')) {
        closePanel();
      } else {
        openPanel();
      }
    });
    filterClose?.addEventListener('click', (event) => {
      event.stopPropagation();
      closePanel();
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closePanel();
      }
    });
  }

  function setupShortcutPanel() {
    if (!helpToggle || !shortcutPanel) return;
    const closePanel = () => {
      shortcutsOpen = false;
      shortcutPanel.classList.remove('shortcut-panel--open');
      shortcutPanel.setAttribute('aria-hidden', 'true');
      helpToggle.setAttribute('aria-expanded', 'false');
    };
    const openPanel = () => {
      shortcutsOpen = true;
      shortcutPanel.classList.add('shortcut-panel--open');
      shortcutPanel.setAttribute('aria-hidden', 'false');
      helpToggle.setAttribute('aria-expanded', 'true');
    };
    helpToggle.addEventListener('click', (event) => {
      event.stopPropagation();
      if (shortcutsOpen) {
        closePanel();
      } else {
        openPanel();
      }
    });
    shortcutClose?.addEventListener('click', (event) => {
      event.stopPropagation();
      closePanel();
    });
    document.addEventListener('click', (event) => {
      if (!shortcutsOpen) return;
      if (shortcutPanel.contains(event.target) || event.target === helpToggle) return;
      closePanel();
    });
  }

  function toggleShortcutPanel(force) {
    if (!shortcutPanel || !helpToggle) return;
    if (typeof force === 'boolean') {
      if (force) {
        if (!shortcutsOpen) {
          helpToggle.click();
        }
      } else if (shortcutsOpen) {
        helpToggle.click();
      }
      return;
    }
    helpToggle.click();
  }

  function setupNotesDrawer() {
    if (!noteDrawer) return;
    const saved = localStorage.getItem('note_drawer_state');
    if (drawerStates.includes(saved)) {
      drawerStateIndex = drawerStates.indexOf(saved);
    }
    applyDrawerState();
    [notesToggle, notesToggleSecondary].forEach((btn) => {
      btn?.addEventListener('click', (event) => {
        event.stopPropagation();
        cycleNoteDrawer();
      });
    });
    noteDrawerCollapse?.addEventListener('click', (event) => {
      event.stopPropagation();
      setNoteDrawerState('collapsed');
    });
  }

  function setupNoteTabs() {
    if (!noteTabs.length) return;
    noteTabs.forEach((btn) => {
      btn.addEventListener('click', () => {
        const tab = btn.dataset.noteTab;
        if (tab) {
          setActiveNoteTab(tab);
        }
      });
    });
    setActiveNoteTab(activeNoteTab);
  }

  function setActiveNoteTab(tab) {
    if (!tab) return;
    activeNoteTab = tab;
    noteTabs.forEach((btn) => {
      const isActive = btn.dataset.noteTab === tab;
      btn.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    notePanels.forEach((panel) => {
      const isActive = panel.dataset.notePanel === tab;
      panel.classList.toggle('note-panel--hidden', !isActive);
    });
  }

  function setupCopyButtons() {
    copyVoiceButton?.addEventListener('click', () => {
      if (!insertVoiceIntoManual()) {
        setStatus('No voice transcripts to copy.', true);
      }
    });
    copyOcrButton?.addEventListener('click', () => {
      if (!insertOcrIntoManual()) {
        setStatus('No OCR text to copy.', true);
      }
    });
  }

  function cycleNoteDrawer(direction = 1) {
    if (!noteDrawer) return;
    drawerStateIndex = (drawerStateIndex + direction + drawerStates.length) % drawerStates.length;
    applyDrawerState();
  }

  function setNoteDrawerState(state) {
    const idx = drawerStates.indexOf(state);
    if (idx === -1 || !noteDrawer) return;
    drawerStateIndex = idx;
    applyDrawerState();
  }

  function applyDrawerState() {
    if (!noteDrawer) return;
    const state = drawerStates[drawerStateIndex];
    noteDrawer.classList.remove('note-drawer--collapsed', 'note-drawer--peek', 'note-drawer--expanded');
    noteDrawer.classList.add(`note-drawer--${state}`);
    const expanded = state === 'collapsed' ? 'false' : 'true';
    noteDrawer.setAttribute('aria-expanded', expanded);
    notesToggle?.setAttribute('aria-expanded', expanded);
    notesToggleSecondary?.setAttribute('aria-expanded', expanded);
    localStorage.setItem('note_drawer_state', state);
  }

  function updateOcrStatusDisplay(bucket) {
    if (!ocrStatusEl) return;
    if (!bucket || !bucket.ocr_status) {
      ocrStatusEl.textContent = '';
      return;
    }
    ocrStatusEl.textContent = `OCR status: ${formatOcrStatus(bucket.ocr_status)}`;
  }

  function runOcrForBucket(variant = 'raw_back') {
    if (!noteInput) return;
    const bucket = state.visible[state.index];
    if (!bucket) {
      setStatus('No bucket selected for OCR.', true);
      return;
    }
    if (variant === 'raw_back' && !bucket.has_back) {
      setStatus('This bucket has no back image to OCR.', true);
      return;
    }
    setStatus('Running OCR…');
    updateNoteStatus('Recognizing text…');
    if (ocrButton) ocrButton.disabled = true;
    fetch('/api/ocr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: bucket.bucket_prefix,
        variant,
      }),
    })
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((payload) => {
        const text = (payload && payload.text ? String(payload.text) : '').trim();
        if (!text) {
          setStatus('OCR returned no text.');
          updateNoteStatus('No text detected');
          return;
        }
        const existing = noteInput.value.trim();
        const combined = existing ? `${existing}\n\n${text}` : text;
        noteInput.value = combined;
        const voiceBlocks = bucket._voiceBlocks || [];
        bucket.note = rebuildNoteFromManual(combined, voiceBlocks);
        bucket.ocr_status = 'draft';
        updateOcrStatusDisplay(bucket);
        updateNoteStatus('Saving…');
        scheduleNoteSave(bucket.bucket_prefix, { ocrStatus: 'draft' });
        setStatus('OCR applied to notes.');
      })
      .catch((err) => {
        setStatus('OCR failed: ' + err.message, true);
        updateNoteStatus('OCR failed', true);
      })
      .finally(() => {
        if (ocrButton) ocrButton.disabled = false;
      });
  }

  function markOcrStatus(status, options = {}) {
    const { advance = false } = options;
    const bucket = state.visible[state.index];
    if (!bucket) return;
    bucket.ocr_status = status;
    updateOcrStatusDisplay(bucket);
    setStatus(`Marking ${formatOcrStatus(status)}…`);
    flushNoteSave();
    saveDecision(bucket, bucket.decision, bucket.note || '', { ocrStatus: status, skipRender: true })
      .then(() => {
        setStatus(`Status set to ${formatOcrStatus(status)}.`);
        updateNoteStatus(bucket.note ? 'Saved' : '');
        if (advance) {
          nextBucket();
        } else {
          render();
        }
      })
      .catch((err) => {
        setStatus('Failed to update status: ' + err.message, true);
      });
  }

  function getVoiceBlocks(bucket) {
    if (!bucket) return [];
    const structured = Array.isArray(bucket.voice_transcripts) ? bucket.voice_transcripts : [];
    const blocks = structured
      .map((entry) => (entry.note_block || '').trim())
      .filter((block) => block.length);
    if (blocks.length) {
      return blocks;
    }
    return detectLegacyVoiceBlocks(bucket.note || '');
  }

  function detectLegacyVoiceBlocks(text) {
    if (!text) return [];
    const matches = [];
    const regex = /(Voice transcript[^\n]*\n[\s\S]*?)(?=(?:\n{2,}Voice transcript|\n{2,}$|$))/gi;
    let match;
    while ((match = regex.exec(text))) {
      matches.push(match[1].trim());
    }
    return matches;
  }

  function stripVoiceBlocks(text, blocks) {
    if (!text || !blocks || !blocks.length) {
      return text ? text.trim() : '';
    }
    let output = text;
    blocks.forEach((block) => {
      output = removeBlock(output, block);
    });
    return output.trim();
  }

  function removeBlock(text, block) {
    if (!block) return text;
    let next = text;
    let idx = next.indexOf(block);
    while (idx !== -1) {
      const before = next.slice(0, idx).trimEnd();
      const after = next.slice(idx + block.length).trimStart();
      next = before && after ? `${before}\n\n${after}` : before || after;
      idx = next.indexOf(block);
    }
    return next;
  }

  function rebuildNoteFromManual(manualText, voiceBlocks) {
    const parts = [];
    const trimmedManual = (manualText || '').trim();
    if (trimmedManual) {
      parts.push(trimmedManual);
    }
    (voiceBlocks || []).forEach((block) => {
      if (block && block.trim()) {
        parts.push(block.trim());
      }
    });
    return parts.join('\n\n');
  }

  function formatTimestamp(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return String(value);
    }
    return date.toLocaleString();
  }

  function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function revealVariant(role) {
    if (!role) return;
    const bucket = state.visible[state.index];
    if (!bucket || !bucket.finder_paths) {
      setStatus('Nothing selected to reveal.', true);
      return;
    }
    const path = bucket.finder_paths[role];
    if (!path) {
      setStatus('No file available for that view.', true);
      return;
    }
    setStatus('Opening in Finder…');
    fetch('/api/reveal', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path }),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        setStatus('Revealed in Finder');
      })
      .catch((err) => {
        setStatus('Reveal failed: ' + err.message, true);
      });
  }

  function renderSourceChips() {
    if (!sourceFiltersEl) return;
    const fragment = document.createDocumentFragment();
    fragment.appendChild(buildChip('All', '__all__', state.filters.sources.size === state.filters.allSources.length));
    state.filters.allSources.forEach((source) => {
      fragment.appendChild(
        buildChip(formatSourceLabel(source), source, state.filters.sources.has(source))
      );
    });
    sourceFiltersEl.innerHTML = '';
    sourceFiltersEl.appendChild(fragment);
  }

  function buildChip(label, value, active) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'chip' + (active ? ' active' : '');
    button.dataset.sourceChip = value;
    button.textContent = label;
    return button;
  }

  const dragState = {
    active: false,
    pointerId: null,
    startX: 0,
    startY: 0,
    panX: 0,
    panY: 0,
    wrapper: null,
  };

  function registerPointerHandlers() {
    if (!bucketContainer) return;
    bucketContainer.addEventListener('pointerdown', handlePointerDown);
    bucketContainer.addEventListener('wheel', handleWheel, { passive: false });
    document.addEventListener('pointermove', handlePointerMove);
    document.addEventListener('pointerup', handlePointerUp);
    document.addEventListener('pointercancel', handlePointerUp);
  }

  function handlePointerDown(event) {
    const wrapper = event.target.closest('[data-zoom-wrapper]');
    if (!wrapper || !isActiveWrapper(wrapper)) return;
    event.preventDefault();
    dragState.active = true;
    dragState.pointerId = event.pointerId;
    dragState.startX = event.clientX;
    dragState.startY = event.clientY;
    dragState.panX = state.pan.x;
    dragState.panY = state.pan.y;
    dragState.wrapper = wrapper;
    wrapper.setPointerCapture?.(event.pointerId);
  }

  function handlePointerMove(event) {
    if (!dragState.active || event.pointerId !== dragState.pointerId) return;
    state.pan = {
      x: dragState.panX + (event.clientX - dragState.startX),
      y: dragState.panY + (event.clientY - dragState.startY),
    };
    applyZoomTransform();
  }

  function handlePointerUp(event) {
    if (!dragState.active || event.pointerId !== dragState.pointerId) return;
    dragState.wrapper?.releasePointerCapture?.(event.pointerId);
    dragState.active = false;
    dragState.wrapper = null;
    dragState.pointerId = null;
    persistPan();
  }

  function handleWheel(event) {
    const wrapper = event.target.closest('[data-zoom-wrapper]');
    if (!wrapper || !isActiveWrapper(wrapper) || !(event.ctrlKey || event.metaKey)) return;
    event.preventDefault();
    const delta = -event.deltaY / 400;
    nudgeZoom(delta);
  }

  function render() {
    const buckets = state.visible;
    if (!buckets.length) {
      bucketContainer.innerHTML = '<p>No buckets match the current filters.</p>';
      summaryEl.textContent = 'No buckets match filters.';
      renderVoiceTranscripts(null);
      renderOcrReadonly(null);
      renderNoteSummary(null);
      emitStateChange('empty');
      return;
    }
    const activeIndex = clampIndex(state.index);
    const bucket = buckets[activeIndex];
    if (!bucket) {
      state.index = clampIndex(activeIndex);
      render();
      return;
    }
    state.index = activeIndex;
    bucketContainer.innerHTML = '';
    const row = document.createElement('section');
    row.className = 'bucket-row active';
    row.dataset.index = activeIndex;
    row.dataset.bucket = bucket.bucket_prefix;
    row.innerHTML = renderRow(bucket, activeIndex);
    bucketContainer.appendChild(row);
    syncNoteEditor(bucket);
    renderVoiceTranscripts(bucket);
    renderOcrReadonly(bucket);
    renderNoteSummary(bucket);
    updateCompareButtons();
    updateSummary();
    updateRotateButtons();
    localStorage.setItem('review_index', String(state.index));
    prefetchImages(state.index + 1);
    syncZoomAnchor();
    scrollActiveRowIntoView();
    emitStateChange('render');
  }

  function renderRow(bucket, idx) {
    const decision = bucket.decision
      ? `<span class="badge badge--decision">${labelFor(bucket.decision)}</span>`
      : '';
    const ocrBadge = bucket.ocr_status
      ? `<span class="badge badge--ocr badge--ocr-${bucket.ocr_status}">${formatOcrStatus(bucket.ocr_status)}</span>`
      : '';
    const caption = bucket.caption ? `<div>${bucket.caption}</div>` : '';
    const keywords = bucket.keywords?.length ? `<div>${bucket.keywords.join(', ')}</div>` : '';
    const originalSrc = sanitize(bucket.web_front || bucket.thumb_front || '');
    const frontFullResAttr = bucket.web_front ? ' data-fullres-variant="raw_front"' : '';
    const originalFinder = buildFinderButton('original', bucket);
    const extras = [renderLinkedBackNotice(bucket), renderDuplicateSection(bucket)]
      .filter(Boolean)
      .join('');
    return `
      <div class="bucket-meta">
        <div class="meta-left">
          <strong>#${idx + 1} · ${bucket.bucket_prefix}</strong>
          <div>${bucket.source}${bucket.group_key ? ' · ' + bucket.group_key : ''}</div>
          ${caption}
          ${keywords}
        </div>
        <div class="badges">
          ${decision}
          ${ocrBadge}
        </div>
      </div>
      ${extras}
      <div class="panes">
        <figure class="pane">
          <div class="zoom-wrapper" data-zoom-wrapper>
            <img class="zoom-canvas" draggable="false" loading="lazy" src="${originalSrc}" alt="Original"
              data-web-src="${originalSrc}"${frontFullResAttr} />
          </div>
          <figcaption>
            <span>Original</span>
            ${originalFinder}
          </figcaption>
        </figure>
        ${renderComparePane(bucket)}
      </div>
    `;
  }

  function renderLinkedBackNotice(bucket) {
    if (!bucket || !bucket.linked_back_bucket) return '';
    return `<div class="linked-back-note">Back linked from bucket ${sanitize(String(bucket.linked_back_bucket))}</div>`;
  }

  function renderDuplicateSection(bucket) {
    const details = bucket && bucket.duplicates;
    const peers = details && Array.isArray(details.peers) ? details.peers : [];
    if (!peers.length) return '';
    const chips = peers
      .map((peer) => {
        const prefix = sanitize(String(peer.bucket_prefix || ''));
        const segments = [];
        if (peer.source) {
          segments.push(formatSourceLabel(peer.source));
        }
        const flags = [];
        if (peer.has_ai) flags.push('AI');
        if (peer.has_back) flags.push('Back');
        if (flags.length) {
          segments.push(flags.join('/'));
        }
        if (peer.decision) {
          const label = labelFor(peer.decision);
          if (label) {
            segments.push(label);
          }
        }
        const meta = segments.length
          ? `<span class="duplicate-chip__meta">${segments.join(' · ')}</span>`
          : '';
        return `<button type="button" class="duplicate-chip" data-duplicate-target="${prefix}">
          <span class="duplicate-chip__title">${prefix}</span>
          ${meta}
        </button>`;
      })
      .join('');
    const total = details && details.group_size ? details.group_size : peers.length + 1;
    return `<div class="duplicate-links">
      <span class="duplicate-links__label">Duplicate set (${total} buckets):</span>
      ${chips}
    </div>`;
  }

  function renderComparePane(bucket) {
    if (state.compareMode === 'back') {
      const backSrc = sanitize(bucket.web_back || bucket.thumb_back || '');
      if (!bucket.has_back || !backSrc) {
        return `<div class="pane pane--empty">No back image attached to this bucket.</div>`;
      }
      const finder = buildFinderButton('back', bucket);
      const rotation = getBackRotation(bucket.bucket_prefix);
      const rotationAttr = ` data-back-rotation="${rotation}"`;
      return `
        <figure class="pane">
          <div class="zoom-wrapper" data-zoom-wrapper>
            <img class="zoom-canvas" draggable="false" loading="lazy" src="${backSrc}" alt="Back"
              data-web-src="${backSrc}"${rotationAttr} />
          </div>
          <figcaption class="pane__caption">
            <div class="pane__caption-left">
              <span class="pane__title">Back</span>
              <div class="back-inline">
                <span class="back-inline__label">Rotate:</span>
                <button type="button" data-back-rotate="ccw" aria-label="Rotate back counter clockwise 90 degrees">↶ 90°</button>
                <button type="button" data-back-rotate="cw" aria-label="Rotate back clockwise 90 degrees">↷ 90°</button>
                <button type="button" data-back-rotate="reset">Reset</button>
                <span class="back-rotation__value" data-rotation-display>${formatRotationLabel(rotation)}</span>
              </div>
            </div>
            <div class="pane__caption-right">
              ${finder}
            </div>
          </figcaption>
        </figure>
      `;
    }
    const aiSrc = sanitize(bucket.web_ai || bucket.thumb_ai || '');
    if (!bucket.has_ai || !aiSrc) {
      return `<div class="pane pane--empty">No AI variant available for this bucket.</div>`;
    }
    const aiVariantAttr = bucket.web_ai ? ' data-fullres-variant="ai_front_v1"' : '';
    const finder = buildFinderButton('ai', bucket);
    return `
      <figure class="pane">
        <div class="zoom-wrapper" data-zoom-wrapper>
          <img class="zoom-canvas" draggable="false" loading="lazy" src="${aiSrc}" alt="AI"
            data-web-src="${aiSrc}"${aiVariantAttr} />
        </div>
        <figcaption>
          <span>AI</span>
          ${finder}
        </figcaption>
      </figure>
    `;
  }

  function renderVoiceTranscripts(bucket) {
    if (!voiceTranscriptList) return;
    if (!bucket) {
      voiceTranscriptList.innerHTML = '<p class="note-muted">No voice transcripts.</p>';
      return;
    }
    const transcripts = Array.isArray(bucket.voice_transcripts) ? bucket.voice_transcripts : [];
    if (!transcripts.length) {
      voiceTranscriptList.innerHTML = '<p class="note-muted">No voice transcripts yet.</p>';
      return;
    }
    const html = transcripts
      .map((entry) => {
        const created = formatTimestamp(entry.created_at);
        const speaker = entry.speaker || 'Speaker';
        const session = entry.session_id ? ` · Session ${escapeHtml(entry.session_id)}` : '';
        const header = `<div class="voice-entry__meta">${escapeHtml(created || '')} · ${escapeHtml(speaker)}${session}</div>`;
        const lines = Array.isArray(entry.entries)
          ? entry.entries
              .map((item) => {
                const label = item.image_id || 'image';
                const text = item.text || '';
                return `<li><strong>${escapeHtml(label)}:</strong> ${escapeHtml(text)}</li>`;
              })
              .join('')
          : '';
        const listHtml = lines ? `<ul>${lines}</ul>` : '';
        const fallback = !lines && entry.note_block ? `<pre>${escapeHtml(entry.note_block)}</pre>` : '';
        return `<div class="voice-entry">${header}${listHtml || fallback || '<p class="note-muted">No text</p>'}</div>`;
      })
      .join('');
    voiceTranscriptList.innerHTML = html;
  }

  function renderOcrReadonly(bucket) {
    if (!ocrReadonlyEl) return;
    if (!bucket) {
      ocrReadonlyEl.innerHTML = '';
      return;
    }
    const segments = [];
    const human = bucket.human_ocr || {};
    if (human.text) {
      const label = human.updated_at ? `Human note · ${formatTimestamp(human.updated_at)}` : 'Human note';
      segments.push(
        `<div class="ocr-section"><div class="ocr-section__label">${escapeHtml(label)}</div><pre>${escapeHtml(
          human.text
        )}</pre></div>`
      );
    }
    const auto = bucket.auto_ocr || {};
    if (auto.front_text) {
      segments.push(
        `<div class="ocr-section"><div class="ocr-section__label">Auto OCR · Front</div><pre>${escapeHtml(
          auto.front_text
        )}</pre></div>`
      );
    }
    if (auto.back_text) {
      segments.push(
        `<div class="ocr-section"><div class="ocr-section__label">Auto OCR · Back</div><pre>${escapeHtml(
          auto.back_text
        )}</pre></div>`
      );
    }
    ocrReadonlyEl.innerHTML = segments.length ? segments.join('') : '<p class="note-muted">No OCR text yet.</p>';
  }

  function renderNoteSummary(bucket) {
    if (!noteSummaryVoice || !noteSummaryOcr || !noteSummaryManual) return;
    const voice = bucket ? summarizeVoice(bucket) : '';
    const ocr = bucket ? summarizeOcr(bucket) : '';
    const manual = bucket ? summarizeManual(bucket) : '';
    setSummaryValue(noteSummaryVoice, voice, 'No voice transcripts.');
    setSummaryValue(noteSummaryOcr, ocr, 'No OCR text yet.');
    setSummaryValue(noteSummaryManual, manual, 'No manual notes.');
    updateNoteBucketChip(bucket);
  }

  function setSummaryValue(node, value, fallback) {
    if (!node) return;
    if (value) {
      node.textContent = value;
      node.classList.remove('note-muted');
    } else {
      node.textContent = fallback;
      node.classList.add('note-muted');
    }
  }

  function updateNoteBucketChip(bucket) {
    if (!noteBucketChip) return;
    if (!bucket) {
      noteBucketChip.textContent = '';
      noteBucketChip.title = '';
      noteBucketChip.classList.add('note-bucket-chip--empty');
      return;
    }
    const parts = [bucket.bucket_prefix];
    if (bucket.group_key) {
      parts.push(bucket.group_key);
    } else if (bucket.source) {
      parts.push(formatSourceLabel(bucket.source));
    }
    const text = parts.join(' · ');
    noteBucketChip.textContent = text;
    noteBucketChip.title = text;
    noteBucketChip.classList.remove('note-bucket-chip--empty');
  }

  function summarizeVoice(bucket) {
    const transcripts = Array.isArray(bucket.voice_transcripts) ? bucket.voice_transcripts : [];
    if (!transcripts.length) return '';
    const entry = transcripts[0];
    if (entry.entries && entry.entries.length) {
      const text = entry.entries[0].text || '';
      return truncateText(text);
    }
    return truncateText(entry.note_block || '');
  }

  function summarizeOcr(bucket) {
    const human = bucket.human_ocr || {};
    if (human.text) {
      return truncateText(human.text);
    }
    const auto = bucket.auto_ocr || {};
    const combined = [auto.front_text, auto.back_text].filter(Boolean).join(' · ');
    return truncateText(combined || '');
  }

  function summarizeManual(bucket) {
    if (!bucket) return '';
    const voiceBlocks = getVoiceBlocks(bucket);
    const manual = stripVoiceBlocks(bucket.note || '', voiceBlocks);
    return truncateText(manual);
  }

  function truncateText(text, maxLength = 160) {
    if (!text) return '';
    const clean = text.replace(/\s+/g, ' ').trim();
    if (clean.length <= maxLength) {
      return clean;
    }
    return `${clean.slice(0, maxLength - 1).trimEnd()}…`;
  }

  function buildFinderButton(role, bucket) {
    if (!bucket.finder_paths) return '';
    const path = bucket.finder_paths[role];
    if (!path) {
      return '';
    }
    let label = 'Show in Finder';
    if (role === 'ai') label = 'Show AI File';
    else if (role === 'back') label = 'Show Back File';
    else label = 'Show Original File';
    return `<button type="button" class="finder-button" data-reveal-role="${role}">${label}</button>`;
  }

  function rotateBack(delta) {
    const bucket = state.visible[state.index];
    if (!canRotateBack(bucket)) return;
    const next = normalizeRotation(getBackRotation(bucket.bucket_prefix) + delta);
    setBackRotation(bucket.bucket_prefix, next);
  }

  function resetBackRotation() {
    const bucket = state.visible[state.index];
    if (!canRotateBack(bucket)) return;
    setBackRotation(bucket.bucket_prefix, 0);
  }

  function setBackRotation(prefix, value) {
    if (!prefix) return;
    const normalized = normalizeRotation(value);
    const entry = state.photoTransforms[prefix] || {
      front: { rotate: 0 },
      back: { rotate: 0 },
    };
    entry.back = { rotate: normalized };
    state.photoTransforms[prefix] = entry;
    render();
    savePhotoTransform(prefix, 'back', normalized);
  }

  function getBackRotation(prefix) {
    if (!prefix) return 0;
    const entry = state.photoTransforms[prefix];
    if (!entry) {
      ensurePhotoTransform(prefix);
      return 0;
    }
    return normalizeRotation(entry?.back?.rotate ?? 0);
  }

  function canRotateBack(bucket) {
    return Boolean(bucket && bucket.has_back && state.compareMode === 'back');
  }

  function normalizeRotation(value) {
    if (!Number.isFinite(value)) return 0;
    let next = value % 360;
    if (next < 0) next += 360;
    return Math.round(next);
  }

  function formatRotationLabel(value) {
    if (!Number.isFinite(value)) return '0°';
    let normalized = value % 360;
    if (normalized < 0) normalized += 360;
    if (normalized > 180) {
      normalized -= 360;
    }
    if (normalized === 0) return '0°';
    return `${normalized > 0 ? '+' : ''}${normalized}°`;
  }

  function updateRotateButtons() {
    const bucket = state.visible[state.index];
    const enabled = canRotateBack(bucket);
    document.querySelectorAll('[data-back-rotate]').forEach((btn) => {
      const action = btn.dataset.backRotate;
      if (action === 'reset') {
        btn.disabled = !enabled || getBackRotation(bucket?.bucket_prefix) === 0;
      } else {
        btn.disabled = !enabled;
      }
    });
    const display = document.querySelector('[data-rotation-display]');
    if (display) {
      const rotation = enabled ? getBackRotation(bucket?.bucket_prefix) : 0;
      display.textContent = formatRotationLabel(rotation);
    }
  }

  function ensurePhotoTransform(prefix) {
    if (!prefix) return Promise.resolve(null);
    if (state.photoTransforms[prefix]) {
      return Promise.resolve(state.photoTransforms[prefix]);
    }
    const existing = state.photoTransformRequests.get(prefix);
    if (existing) return existing;
    const request = fetch(`/api/photo/transform?bucket_prefix=${encodeURIComponent(prefix)}`)
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `HTTP ${response.status}`);
        }
        return response.json();
      })
      .then((payload) => {
        const front = payload?.front || { rotate: 0 };
        const back = payload?.back || { rotate: 0 };
        state.photoTransforms[prefix] = {
          front: { rotate: normalizeRotation(front.rotate) },
          back: { rotate: normalizeRotation(back.rotate) },
        };
        render();
        return state.photoTransforms[prefix];
      })
      .catch(() => null)
      .finally(() => {
        state.photoTransformRequests.delete(prefix);
      });
    state.photoTransformRequests.set(prefix, request);
    return request;
  }

  function savePhotoTransform(prefix, side, rotation) {
    if (!prefix || !side) return Promise.resolve();
    return fetch('/api/photo/transform', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bucket_prefix: prefix,
        side,
        rotate: rotation,
      }),
    })
      .then(async (response) => {
        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || `HTTP ${response.status}`);
        }
        return response.json();
      })
      .catch((err) => {
        setStatus('Failed to save rotation: ' + err.message, true);
      });
  }

  function applyDecision(choice) {
    const bucket = state.visible[state.index];
    if (!bucket) return;
    state.history.push({
      bucket_prefix: bucket.bucket_prefix,
      previous: bucket.decision || null,
      note: bucket.note || '',
    });
    bucket.decision = choice;
    saveDecision(bucket, choice, bucket.note || '');
    nextBucket();
  }

  function undoDecision() {
    const last = state.history.pop();
    if (!last) return;
    const bucket = state.buckets.find((b) => b.bucket_prefix === last.bucket_prefix);
    if (!bucket) return;
    bucket.decision = last.previous;
    bucket.note = last.note;
    saveDecision(bucket, last.previous, last.note, { silent: true });
    render();
  }

  function saveDecision(bucket, choice, note, options = {}) {
    const { silent = false, skipRender = false, ocrStatus } = options;
    const payload = {
      bucket_prefix: bucket.bucket_prefix,
      note: note || '',
    };
    if (choice) {
      payload.choice = choice;
    } else {
      payload.clear = true;
    }
    if (typeof ocrStatus === 'string' && ocrStatus.length) {
      payload.ocr_status = ocrStatus;
    }
    const request = fetch('/api/decision', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
      })
      .catch((err) => {
        if (!silent) {
          setStatus('Failed to save decision: ' + err, true);
        }
        throw err;
      });
    if (!skipRender) {
      render();
    }
    return request;
  }

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

  function jumpPrompt() {
    const input = prompt('Jump to bucket number (1-based)');
    if (!input) return;
    const idx = clampIndex(parseInt(input, 10) - 1);
    state.index = idx;
    render();
  }

  function focusBucketByPrefix(prefix) {
    const target = (prefix || '').trim();
    if (!target) return;
    let idx = state.visible.findIndex((b) => b.bucket_prefix === target);
    if (idx === -1) {
      const bucket = state.buckets.find((b) => b.bucket_prefix === target);
      if (!bucket) {
        setStatus(`Bucket ${target} is not loaded in this session.`, true);
        return;
      }
      const normalizedSource = normalizeSource(bucket.source);
      if (!state.filters.sources.has(normalizedSource)) {
        state.filters.sources.add(normalizedSource);
        persistSources();
        renderSourceChips();
      }
      if (state.variantFilter && !matchesVariantFilter(bucket, state.variantFilter)) {
        state.variantFilter = null;
        persistVariantFilter();
        updateVariantFilterButtons();
      }
      applyFilters({ skipRender: true, skipStatusClear: true });
      idx = state.visible.findIndex((b) => b.bucket_prefix === target);
    }
    if (idx === -1) {
      setStatus(`Bucket ${target} is hidden by current filters.`, true);
      return;
    }
    state.index = clampIndex(idx);
    render();
  }

  function prefetchImages(idx) {
    for (let i = idx; i < Math.min(idx + 2, state.visible.length); i += 1) {
      const bucket = state.visible[i];
      if (!bucket) continue;
      ['web_front', 'web_ai', 'web_back'].forEach((key) => {
        const src = bucket[key];
        if (src) {
          const img = new Image();
          img.src = sanitize(src);
        }
      });
    }
  }

  function updateSummary() {
    const decided = state.buckets.filter((b) => b.decision).length;
    const filteredNote =
      state.visible.length !== state.buckets.length
        ? ` (filtered from ${state.buckets.length})`
        : '';
    const current = state.visible[state.index];
    const extraMeta = [];
    if (current?.bucket_prefix) {
      extraMeta.push(current.bucket_prefix);
    }
    if (current?.source) {
      extraMeta.push(formatSourceLabel(current.source));
    }
    if (current?.group_key) {
      extraMeta.push(current.group_key);
    }
    const metaText = extraMeta.length ? ` · ${extraMeta.join(' · ')}` : '';
    summaryEl.textContent = `Bucket ${state.visible.length ? state.index + 1 : 0} / ${state.visible.length}${filteredNote} · Decisions ${decided}${metaText}`;
    if (shortcutBar) {
      shortcutBar.textContent =
        'Shortcuts: J/K navigate · 1 Original · 2 AI · 3 Flag · V verify+next · +/- zoom · 0 reset · H full-res · U undo · G go to bucket · Drag to pan · Ctrl/⌘ + scroll or slider to zoom';
    }
  }

  function onStateChange(callback) {
    if (typeof callback !== 'function') {
      return () => {};
    }
    stateChangeCallbacks.add(callback);
    return () => {
      stateChangeCallbacks.delete(callback);
    };
  }

  function emitStateChange(reason) {
    const snapshot = getCurrentState();
    snapshot.sessionId = sessionId;
    const flagged = snapshot.bucketId ? consumePendingNoteFlag() : false;
    snapshot.noteFlag = flagged;
    snapshot.reason = reason || snapshot.reason || null;
    const signature = `${snapshot.bucketId || 'none'}::${snapshot.imageId || 'none'}::${snapshot.compareMode || 'none'}::${snapshot.noteFlag ? '1' : '0'}`;
    updateStateOverlay(snapshot);
    if (signature === lastStateSignature) {
      return;
    }
    lastStateSignature = signature;
    stateChangeCallbacks.forEach((callback) => {
      try {
        callback(snapshot);
      } catch (error) {
        console.error('state change callback failed', error);
      }
    });
    window.dispatchEvent(new CustomEvent('photo:change', { detail: snapshot }));
    postStateSnapshot(snapshot);
  }

  function getCurrentState() {
    const total = state.visible.length;
    const clampedIndex = clampIndex(state.index);
    const base = {
      sessionId,
      bucketId: null,
      bucketSource: null,
      imageId: null,
      variant: null,
      primaryVariant: 'raw_front',
      compareVariant: null,
      compareMode: state.compareMode,
      index: clampedIndex,
      total,
      bucketPosition: total ? clampedIndex + 1 : 0,
      path: null,
      primaryPath: null,
      comparePath: null,
      webPath: null,
      timestamp: Date.now(),
      hasBack: false,
      hasAi: false,
      noteFlag: false,
    };
    if (!total) {
      return base;
    }
    const bucket = state.visible[clampedIndex];
    const finderPaths = bucket.finder_paths || {};
    base.bucketId = bucket.bucket_prefix || null;
    base.bucketSource = bucket.source || null;
    base.hasBack = Boolean(bucket.has_back);
    base.hasAi = Boolean(bucket.has_ai);
    base.primaryPath = finderPaths.original || null;
    let compareVariant = null;
    let comparePath = null;
    if (state.compareMode === 'back' && bucket.has_back) {
      compareVariant = 'raw_back';
      comparePath = finderPaths.back || null;
      base.webPath = bucket.web_back || null;
    } else if (state.compareMode !== 'back' && bucket.has_ai) {
      compareVariant = 'ai_front_v1';
      comparePath = finderPaths.ai || null;
      base.webPath = bucket.web_ai || null;
    } else {
      base.webPath = bucket.web_front || null;
    }
    base.compareVariant = compareVariant;
    base.comparePath = comparePath;
    base.variant = compareVariant || 'raw_front';
    base.imageId = base.bucketId ? `${base.bucketId}:${base.variant}` : null;
    base.path = comparePath || base.primaryPath || null;
    if (!base.webPath) {
      base.webPath = bucket.web_front || null;
    }
    return base;
  }

  function postStateSnapshot(snapshot) {
    if (!snapshot.bucketId) {
      return;
    }
    const payload = JSON.stringify(snapshot);
    if (navigator.sendBeacon) {
      const blob = new Blob([payload], { type: 'application/json' });
      if (navigator.sendBeacon('/api/state_update', blob)) {
        return;
      }
    }
    fetch('/api/state_update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true,
    }).catch((error) => {
      console.debug('State sync failed', error);
    });
  }

  function updateStateOverlay(snapshot) {
    if (!stateOverlay) return;
    stateOverlay.classList.remove('state-overlay--idle', 'state-overlay--flagged', 'state-overlay--armed');
    if (!snapshot.bucketId) {
      stateOverlay.textContent = 'No bucket loaded';
      stateOverlay.classList.add('state-overlay--idle');
      return;
    }
    const compareText = snapshot.compareVariant ? ` · ${snapshot.compareVariant}` : '';
    const flagText = snapshot.noteFlag
      ? ' · FLAG'
      : pendingNoteFlag
        ? ' · FLAG ARMED'
        : '';
    stateOverlay.textContent = `${snapshot.bucketId}${compareText}${flagText}`;
    if (snapshot.noteFlag) {
      stateOverlay.classList.add('state-overlay--flagged');
    } else if (pendingNoteFlag) {
      stateOverlay.classList.add('state-overlay--armed');
    }
  }

  function setStatus(message, isError = false) {
    if (!statusBar) return;
    statusBar.textContent = message || '';
    statusBar.classList.toggle('status-bar--error', Boolean(message && isError));
    if (!message) {
      statusBar.classList.remove('status-bar--error');
    }
  }

  function matchesVariantFilter(bucket, filter) {
    switch (filter) {
      case 'has_back':
        return Boolean(bucket.has_back);
      case 'has_ai':
        return Boolean(bucket.has_ai);
      case 'missing_ai':
        return !bucket.has_ai;
      default:
        return true;
    }
  }

  function labelFor(choice) {
    switch (choice) {
      case 'prefer_ai':
        return 'AI';
      case 'prefer_original':
        return 'Original';
      case 'flag_creepy':
        return 'Flagged';
      default:
        return '';
    }
  }

  function formatOcrStatus(status) {
    switch (status) {
      case 'machine':
        return 'Machine';
      case 'draft':
        return 'Draft';
      case 'verified':
        return 'Verified';
      default:
        return status || '';
    }
  }

  function clampIndex(value) {
    const len = state.visible.length;
    if (!len) return 0;
    if (Number.isNaN(value) || value < 0) return 0;
    if (value >= len) return len - 1;
    return value;
  }

  function sanitize(value) {
    if (!value) return '';
    return value.replace(/\\/g, '/');
  }

  function normalizeSource(value) {
    if (typeof value === 'string' && value.trim().length) {
      return value;
    }
    return 'unknown';
  }

  function formatSourceLabel(value) {
    const safe = value || 'unknown';
    return safe
      .split('_')
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(' ');
  }

  function parseStoredArray(key) {
    try {
      const raw = JSON.parse(localStorage.getItem(key) || 'null');
      return Array.isArray(raw) ? raw : [];
    } catch (_) {
      return [];
    }
  }

  function createSessionId() {
    if (window.crypto && typeof window.crypto.randomUUID === 'function') {
      return window.crypto.randomUUID();
    }
    const rand = Math.random().toString(36).slice(2, 10);
    return `sess_${Date.now().toString(36)}_${rand}`;
  }

  function parseStoredPan() {
    try {
      const raw = JSON.parse(localStorage.getItem('review_pan') || 'null');
      if (raw && typeof raw.x === 'number' && typeof raw.y === 'number') {
        return raw;
      }
    } catch (_) {
      // ignore
    }
    return { x: 0, y: 0 };
  }

  function parseVariantFilter(value) {
    if (value === 'has_back' || value === 'has_ai' || value === 'missing_ai') {
      return value;
    }
    return null;
  }

  function clampZoom(value) {
    if (Number.isNaN(value)) return MIN_ZOOM;
    return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, value));
  }

  function persistSources() {
    localStorage.setItem('review_sources', JSON.stringify(Array.from(state.filters.sources)));
  }

  function persistVariantFilter() {
    if (state.variantFilter) {
      localStorage.setItem('review_variant_filter', state.variantFilter);
    } else {
      localStorage.removeItem('review_variant_filter');
    }
  }

  function persistZoom() {
    localStorage.setItem('review_zoom', String(state.zoom));
    updateZoomValue();
  }

  function persistPan() {
    localStorage.setItem('review_pan', JSON.stringify(state.pan));
  }

  function updateZoomValue() {
    if (zoomValue) {
      zoomValue.textContent = state.zoom.toFixed(1) + '×';
    }
  }

  function applyZoomTransform() {
    if (!bucketContainer) return;
    const canvases = bucketContainer.querySelectorAll('.zoom-canvas');
    canvases.forEach((img) => {
      img.style.transform = '';
    });
    const activeRow = bucketContainer.querySelector('.bucket-row.active');
    if (!activeRow) {
      updateZoomValue();
      return;
    }
    const activeCanvases = activeRow.querySelectorAll('.zoom-canvas');
    activeCanvases.forEach((img) => {
      const panZoom = `translate(${state.pan.x}px, ${state.pan.y}px) scale(${state.zoom})`;
      const rotation = Number(img.dataset.backRotation || 0) || 0;
      const fitScale = getRotationFitScale(img, rotation);
      const rotateSegment = rotation ? ` rotate(${rotation}deg)` : '';
      const scaleSegment = fitScale !== 1 ? ` scale(${fitScale})` : '';
      img.style.transform = `${panZoom}${scaleSegment}${rotateSegment}`;
    });
    updateZoomValue();
  }

  function getRotationFitScale(img, rotation) {
    if (!rotation || rotation % 180 === 0) {
      return 1;
    }
    const wrapper = img.closest('.zoom-wrapper');
    if (!wrapper) {
      return 1;
    }
    const imgWidth = img.naturalWidth || img.width || 1;
    const imgHeight = img.naturalHeight || img.height || 1;
    const wrapperWidth = wrapper.clientWidth || imgWidth;
    const wrapperHeight = wrapper.clientHeight || imgHeight;
    const scaleX = wrapperWidth / imgHeight;
    const scaleY = wrapperHeight / imgWidth;
    const fit = Math.min(scaleX, scaleY);
    if (!Number.isFinite(fit) || fit <= 0) {
      return 1;
    }
    return fit;
  }

  function refreshFullResSources() {
    if (!bucketContainer) return;
    const rows = bucketContainer.querySelectorAll('.bucket-row');
    rows.forEach(resetRowImages);
    if (!state.fullRes) {
      return;
    }
    const activeRow = bucketContainer.querySelector('.bucket-row.active');
    if (activeRow) {
      applyFullResToRow(activeRow);
    }
  }

  function resetRowImages(row) {
    const images = row.querySelectorAll('.zoom-canvas');
    images.forEach((img) => {
      const current = img.dataset.webSrc;
      if (!current) return;
      if (img.dataset.fullresKey) {
        releaseFullRes(img.dataset.fullresKey);
        img.dataset.fullresKey = '';
      }
      if (img.src !== current) {
        img.src = current;
      }
    });
  }

  function applyFullResToRow(row) {
    const bucketPrefix = row.dataset.bucket;
    if (!bucketPrefix) return;
    const images = row.querySelectorAll('.zoom-canvas');
    images.forEach((img) => {
      const variant = img.dataset.fullresVariant;
      if (!variant) return;
      loadFullResImage(bucketPrefix, variant)
        .then(({ key, url }) => {
          if (!state.fullRes) return;
          if (!row.classList.contains('active')) return;
          if (img.dataset.fullresKey && img.dataset.fullresKey !== key) {
            releaseFullRes(img.dataset.fullresKey);
          }
          img.dataset.fullresKey = key;
          const cache = fullResCache.get(key);
          if (cache) {
            cache.refs += 1;
          }
          if (img.src !== url) {
            img.src = url;
          }
          applyZoomTransform();
        })
        .catch((err) => {
          setStatus('Failed to load full resolution image: ' + err.message, true);
        });
    });
  }

  async function loadFullResImage(bucketPrefix, variant) {
    const key = `${bucketPrefix}:${variant}`;
    let entry = fullResCache.get(key);
    if (entry && entry.url) {
      return { key, url: entry.url };
    }
    const response = await fetch(
      `/api/fullres?bucket=${encodeURIComponent(bucketPrefix)}&variant=${encodeURIComponent(variant)}`
    );
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    entry = { url, refs: 0 };
    fullResCache.set(key, entry);
    return { key, url };
  }

  function releaseFullRes(key) {
    if (!key) return;
    const entry = fullResCache.get(key);
    if (!entry) return;
    entry.refs = Math.max(0, entry.refs - 1);
  }

  function flushFullResCache() {
    fullResCache.forEach((entry) => {
      URL.revokeObjectURL(entry.url);
    });
    fullResCache.clear();
  }

  window.addEventListener('beforeunload', () => {
    flushFullResCache();
  });

  function applyFilters(options = {}) {
    const desired = state.filters.sources;
    if (!desired.size) {
      state.filters.sources = new Set(state.filters.allSources);
    }
    const base = state.buckets.filter((bucket) => desired.has(normalizeSource(bucket.source)));
    let nextVisible = base;
    if (state.variantFilter) {
      nextVisible = nextVisible.filter((bucket) => matchesVariantFilter(bucket, state.variantFilter));
    }
    state.visible = nextVisible;
    if (!state.visible.length) {
      if (!base.length) {
        state.filters.sources = new Set(state.filters.allSources);
        state.visible = state.buckets.slice();
        if (!options.skipFilterPersistence) {
          persistSources();
        }
        renderSourceChips();
      }
      setStatus('No buckets match the current filters.', true);
    } else if (!options.skipStatusClear) {
      setStatus('');
    }
    const targetIndex =
      typeof options.initialIndex === 'number' && !Number.isNaN(options.initialIndex)
        ? options.initialIndex
        : state.index;
    state.index = clampIndex(targetIndex);
    if (!options.skipRender) {
      render();
    }
  }

  function toggleFullRes(force, options = {}) {
    const shouldRefresh = !options.skipFullRes;
    const next = typeof force === 'boolean' ? force : !state.fullRes;
    if (state.fullRes === next) {
      if (shouldRefresh) {
        refreshFullResSources();
      }
      return;
    }
    state.fullRes = next;
    localStorage.setItem('review_fullres', state.fullRes ? '1' : '0');
    updateFullResButton();
    if (shouldRefresh) {
      refreshFullResSources();
    }
    if (!state.fullRes) {
      flushFullResCache();
    }
  }

  function updateFullResButton() {
    if (!fullResToggle) return;
    fullResToggle.setAttribute('aria-pressed', state.fullRes ? 'true' : 'false');
    fullResToggle.textContent = state.fullRes ? 'AI Full Res ON' : 'AI Full Res OFF';
  }

  function syncZoomAnchor() {
    const active = state.visible[state.index];
    const key = active ? active.bucket_prefix : null;
    if (key !== zoomAnchor) {
      zoomAnchor = key;
      resetZoomState();
    } else {
      applyZoomTransform();
    }
    refreshFullResSources();
  }

  function scrollActiveRowIntoView() {
    if (!bucketContainer) return;
    const activeRow = bucketContainer.querySelector('.bucket-row.active');
    if (!activeRow) return;
    const rowTop = activeRow.offsetTop;
    const rowBottom = rowTop + activeRow.offsetHeight;
    const viewTop = bucketContainer.scrollTop;
    const viewBottom = viewTop + bucketContainer.clientHeight;
    if (rowTop < viewTop + 12) {
      bucketContainer.scrollTo({ top: Math.max(rowTop - 12, 0), behavior: 'auto' });
    } else if (rowBottom > viewBottom - 12) {
      bucketContainer.scrollTo({ top: rowBottom - bucketContainer.clientHeight + 12, behavior: 'auto' });
    }
  }

  function nudgeZoom(delta) {
    const next = clampZoom(Math.round((state.zoom + delta) * 10) / 10);
    setZoom(next);
  }

  function resetZoomState() {
    setPan({ x: 0, y: 0 }, { applyTransform: false });
    setZoom(1, { applyTransform: false });
    applyZoomTransform();
  }

  function setZoom(value, options = {}) {
    const { applyTransform = true } = options;
    const next = clampZoom(value);
    if (next === state.zoom) {
      updateZoomValue();
      return;
    }
    state.zoom = next;
    if (zoomSlider) {
      zoomSlider.value = state.zoom.toFixed(2);
    }
    persistZoom();
    if (applyTransform) {
      applyZoomTransform();
    } else {
      updateZoomValue();
    }
  }

  function setPan(value, options = {}) {
    const { applyTransform = true } = options;
    state.pan = value;
    persistPan();
    if (applyTransform) {
      applyZoomTransform();
    }
  }

  function isActiveWrapper(wrapper) {
    const row = wrapper.closest('.bucket-row');
    return row?.classList.contains('active');
  }
})();
