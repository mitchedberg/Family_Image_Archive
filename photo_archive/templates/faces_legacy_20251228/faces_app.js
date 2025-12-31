(function () {
  const DATA = window.FACES_DATA || {};
  const faces = Array.isArray(DATA.faces) ? DATA.faces.slice() : [];
  const sources = Array.isArray(DATA.sources) ? DATA.sources.slice() : [];

  const summaryEl = document.getElementById('summary');
  const gridEl = document.getElementById('faces-grid');
  const sourceChipsEl = document.getElementById('source-chips');
  const confidenceSlider = document.getElementById('confidence-slider');
  const confidenceValue = document.getElementById('confidence-value');
  const searchInput = document.getElementById('label-filter');

  if (!faces.length) {
    if (summaryEl) summaryEl.textContent = 'No face detections available.';
    return;
  }

  const storedSources = parseStoredArray('faces_sources');
  const activeSources =
    storedSources.length && storedSources.every((value) => sources.includes(value))
      ? new Set(storedSources)
      : new Set(sources);

  const state = {
    faces,
    filters: {
      allSources: sources,
      sources: activeSources,
      minConfidence: clampConfidence(
        parseFloat(localStorage.getItem('faces_min_confidence') || `${DATA.min_confidence || 0.35}`)
      ),
      search: '',
    },
  };

  setupControls();
  render();

  function setupControls() {
    if (confidenceSlider) {
      confidenceSlider.value = state.filters.minConfidence.toFixed(2);
      setConfidenceValue();
      confidenceSlider.addEventListener('input', (event) => {
        const next = clampConfidence(parseFloat(event.target.value));
        state.filters.minConfidence = next;
        localStorage.setItem('faces_min_confidence', next.toFixed(2));
        setConfidenceValue();
        render();
      });
    }
    if (searchInput) {
      searchInput.addEventListener('input', (event) => {
        state.filters.search = event.target.value.trim().toLowerCase();
        render();
      });
    }
    if (sourceChipsEl) {
      sourceChipsEl.addEventListener('click', (event) => {
        const button = event.target.closest('button[data-source]');
        if (!button) return;
        const value = button.dataset.source;
        if (value === '__all__') {
          state.filters.sources = new Set(state.filters.allSources);
        } else if (state.filters.sources.has(value)) {
          state.filters.sources.delete(value);
          if (!state.filters.sources.size) {
            state.filters.sources = new Set(state.filters.allSources);
          }
        } else {
          state.filters.sources.add(value);
        }
        persistSources();
        renderSourceChips();
        render();
      });
      renderSourceChips();
    }
  }

  function render() {
    const visible = state.faces.filter(applyFilters);
    const labeled = state.faces.filter((face) => face.label && face.label.length).length;
    if (summaryEl) {
      summaryEl.textContent = `Showing ${visible.length.toLocaleString()} of ${state.faces.length.toLocaleString()} faces · Labeled ${labeled.toLocaleString()} · Min confidence ${state.filters.minConfidence.toFixed(
        2
      )}`;
    }
    if (!gridEl) return;
    gridEl.innerHTML = '';
    const fragment = document.createDocumentFragment();
    visible.forEach((face) => {
      fragment.appendChild(buildFaceCard(face));
    });
    gridEl.appendChild(fragment);
  }

  function buildFaceCard(face) {
    const card = document.createElement('article');
    card.className = 'face-card';
    card.dataset.faceId = face.face_id;

    const meta = document.createElement('header');
    meta.className = 'face-card__meta';
    meta.innerHTML = `<span>${face.source} · ${face.bucket_prefix} · #${face.face_index}</span><span>${face.confidence.toFixed(
      2
    )}</span>`;
    card.appendChild(meta);

    if (face.image) {
      const imageWrapper = document.createElement('div');
      imageWrapper.className = 'face-card__image';
      const img = document.createElement('img');
      img.src = face.image;
      img.alt = `${face.bucket_prefix} preview`;
      imageWrapper.appendChild(img);
      const box = document.createElement('div');
      box.className = 'face-card__box';
      const bbox = face.bbox || {};
      box.style.left = `${(bbox.left || 0) * 100}%`;
      box.style.top = `${(bbox.top || 0) * 100}%`;
      box.style.width = `${(bbox.width || 0) * 100}%`;
      box.style.height = `${(bbox.height || 0) * 100}%`;
      imageWrapper.appendChild(box);
      card.appendChild(imageWrapper);
    }

    const label = document.createElement('div');
    label.className = face.label ? 'face-card__label' : 'face-card__label face-card__label--empty';
    label.textContent = face.label || 'Unlabeled';
    card.appendChild(label);

    const actions = document.createElement('div');
    actions.className = 'face-card__actions';
    const labelBtn = document.createElement('button');
    labelBtn.type = 'button';
    labelBtn.textContent = face.label ? 'Rename' : 'Label';
    labelBtn.addEventListener('click', () => handleLabel(face, labelBtn, clearBtn));
    actions.appendChild(labelBtn);

    const clearBtn = document.createElement('button');
    clearBtn.type = 'button';
    clearBtn.textContent = 'Clear';
    clearBtn.disabled = !face.label;
    clearBtn.addEventListener('click', () => handleClear(face, labelBtn, clearBtn));
    actions.appendChild(clearBtn);

    card.appendChild(actions);
    return card;
  }

  function handleLabel(face, labelBtn, clearBtn) {
    const value = prompt(`Label for ${face.bucket_prefix} · face ${face.face_index}`, face.label || '');
    if (value === null) return;
    const label = value.trim();
    if (!label) return;
    persistLabel(face, label, labelBtn, clearBtn);
  }

  function handleClear(face, labelBtn, clearBtn) {
    if (!face.label) return;
    if (!confirm(`Clear label for ${face.bucket_prefix} · face ${face.face_index}?`)) {
      return;
    }
    persistClear(face, labelBtn, clearBtn);
  }

  async function persistLabel(face, label, labelBtn, clearBtn) {
    setBusy(true, labelBtn, clearBtn);
    try {
      const response = await fetch('/api/face-tag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          face_id: face.face_id,
          bucket_prefix: face.bucket_prefix,
          face_index: face.face_index,
          label,
        }),
      });
      const payload = await response.json();
      if (!response.ok || payload.status !== 'ok') {
        throw new Error(payload.error || 'Failed to save label');
      }
      face.label = payload.tag.label || label;
      render();
    } catch (error) {
      alert(error.message || error);
    } finally {
      setBusy(false, labelBtn, clearBtn);
    }
  }

  async function persistClear(face, labelBtn, clearBtn) {
    setBusy(true, labelBtn, clearBtn);
    try {
      const response = await fetch('/api/face-tag', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          face_id: face.face_id,
          clear: true,
        }),
      });
      const payload = await response.json();
      if (!response.ok || payload.status !== 'cleared') {
        throw new Error(payload.error || 'Failed to clear label');
      }
      face.label = '';
      render();
    } catch (error) {
      alert(error.message || error);
    } finally {
      setBusy(false, labelBtn, clearBtn);
    }
  }

  function applyFilters(face) {
    if (face.confidence < state.filters.minConfidence) {
      return false;
    }
    if (state.filters.sources.size && !state.filters.sources.has(face.source)) {
      return false;
    }
    if (!state.filters.search) {
      return true;
    }
    const haystack = `${face.label || ''} ${face.bucket_prefix} ${face.source}`.toLowerCase();
    return haystack.includes(state.filters.search);
  }

  function renderSourceChips() {
    if (!sourceChipsEl) return;
    const fragment = document.createDocumentFragment();
    fragment.appendChild(
      buildChip('All', '__all__', state.filters.sources.size === state.filters.allSources.length)
    );
    state.filters.allSources.forEach((source) => {
      fragment.appendChild(buildChip(source, source, state.filters.sources.has(source)));
    });
    sourceChipsEl.innerHTML = '';
    sourceChipsEl.appendChild(fragment);
  }

  function buildChip(label, value, active) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = active ? 'chip active' : 'chip';
    button.textContent = label;
    button.dataset.source = value;
    return button;
  }

  function setConfidenceValue() {
    if (confidenceValue) {
      confidenceValue.textContent = state.filters.minConfidence.toFixed(2);
    }
  }

  function clampConfidence(value) {
    if (Number.isNaN(value)) return 0;
    return Math.min(1, Math.max(0, value));
  }

  function setBusy(isBusy, ...buttons) {
    buttons.forEach((button) => {
      if (!button) return;
      button.disabled = isBusy;
    });
  }

  function parseStoredArray(key) {
    try {
      const cached = JSON.parse(localStorage.getItem(key) || '[]');
      return Array.isArray(cached) ? cached : [];
    } catch (error) {
      return [];
    }
  }

  function persistSources() {
    const values = Array.from(state.filters.sources);
    localStorage.setItem('faces_sources', JSON.stringify(values));
  }
})();
