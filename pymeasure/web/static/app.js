/**
 * app.js — Frontend JavaScript for Flask + SocketIO + Bokeh lab instrument control GUI
 */

'use strict';

// ---------------------------------------------------------------------------
// Global state
// ---------------------------------------------------------------------------

/** Map<experiment_id, {filename, filepath, status, status_label, progress, color, params}> */
const experiments = new Map();

/** Map<experiment_id, {xs: [], ys: [], lastCount: number}> */
const plotSources = {};

/** Map<experiment_id, intervalId> */
const pollingIntervals = new Map();

// window.bokehSources is expected to be populated by the Bokeh glue code in
// the template:  window.bokehSources = {};
// Each entry: window.bokehSources[experiment_id] = <Bokeh ColumnDataSource>

// ---------------------------------------------------------------------------
// SocketIO connection
// ---------------------------------------------------------------------------

const socket = io();

socket.on('connect', () => {
    console.log('SocketIO connected:', socket.id);
});

socket.on('disconnect', () => {
    console.log('SocketIO disconnected');
});

// ---------------------------------------------------------------------------
// SocketIO event handlers
// ---------------------------------------------------------------------------

socket.on('experiment_queued', (data) => {
    const { experiment_id, filename, filepath, status, status_label, progress, color, params } = data;

    // Store in map
    experiments.set(experiment_id, { filename, filepath, status, status_label, progress, color, params });

    // Initialize plot tracking
    plotSources[experiment_id] = { xs: [], ys: [], lastCount: 0 };

    // Add row to browser table
    addBrowserTableRow(experiment_id, data);

    // Register Bokeh source slot. Retry briefly in case Bokeh document
    // hasn't finished initializing when the first event arrives.
    function tryAddCurve(attemptsLeft) {
        if (typeof window.addCurveToPlot !== 'function') return;
        var docs = (typeof Bokeh !== 'undefined') ? Bokeh.documents : [];
        if (docs && docs.length > 0 && docs[0].roots().length > 0) {
            window.addCurveToPlot(experiment_id, color, filename);
        } else if (attemptsLeft > 0) {
            setTimeout(function() { tryAddCurve(attemptsLeft - 1); }, 100);
        }
    }
    tryAddCurve(20);
});

socket.on('experiment_running', (data) => {
    const { experiment_id } = data;
    updateStatusBadge(experiment_id, 'Running', 'badge-running');
    startPolling(experiment_id);
});

socket.on('experiment_finished', (data) => {
    const { experiment_id } = data;
    updateStatusBadge(experiment_id, 'Finished', 'badge-finished');
    stopPolling(experiment_id);
    fetchData(experiment_id, true);
    updateProgressBar(experiment_id, 100);
});

socket.on('experiment_failed', (data) => {
    const { experiment_id } = data;
    updateStatusBadge(experiment_id, 'Failed', 'badge-failed');
    stopPolling(experiment_id);
    enableResumeButton(experiment_id);
});

socket.on('experiment_aborted', (data) => {
    const { experiment_id } = data;
    updateStatusBadge(experiment_id, 'Aborted', 'badge-aborted');
    stopPolling(experiment_id);
    enableResumeButton(experiment_id);
});

socket.on('experiment_removed', (data) => {
    const { experiment_id } = data;
    removeBrowserTableRow(experiment_id);
    removeCurveFromPlot(experiment_id);
    experiments.delete(experiment_id);
    delete plotSources[experiment_id];
});

socket.on('progress', (data) => {
    const { experiment_id, value } = data;
    updateProgressBar(experiment_id, value);
    if (experiments.has(experiment_id)) {
        experiments.get(experiment_id).progress = value;
    }
});

socket.on('status', (data) => {
    // Lifecycle events handle most status changes; this is a no-op / debug
    const { experiment_id, value } = data;
    if (experiments.has(experiment_id)) {
        experiments.get(experiment_id).status = value;
    }
});

socket.on('log', (data) => {
    const { experiment_id, message, levelname } = data;
    const logOutput = document.getElementById('log-output');
    if (!logOutput) return;
    const line = document.createTextNode(`[${levelname}] ${message}\n`);
    logOutput.appendChild(line);
    logOutput.scrollTop = logOutput.scrollHeight;
});

// ---------------------------------------------------------------------------
// Browser table helpers
// ---------------------------------------------------------------------------

function rowId(experiment_id) {
    return `row-${CSS.escape(String(experiment_id))}`;
}

function addBrowserTableRow(experiment_id, data) {
    const tbody = document.querySelector('#browser-table tbody');
    if (!tbody) return;

    const tr = document.createElement('tr');
    tr.id = rowId(experiment_id);
    tr.dataset.experimentId = experiment_id;

    // Column 0: visibility checkbox
    const tdVis = document.createElement('td');
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = true;
    checkbox.title = 'Show/hide curve';
    checkbox.addEventListener('change', () => {
        setCurveVisible(experiment_id, checkbox.checked);
    });
    tdVis.appendChild(checkbox);
    tr.appendChild(tdVis);

    // Column 1: color swatch
    const tdColor = document.createElement('td');
    const swatch = document.createElement('span');
    swatch.className = 'color-swatch';
    swatch.style.background = data.color || '#888';
    tdColor.appendChild(swatch);
    tr.appendChild(tdColor);

    // Column 2: filename
    const tdName = document.createElement('td');
    tdName.textContent = data.filename || '';
    tr.appendChild(tdName);

    // Column 3: status badge
    const tdStatus = document.createElement('td');
    const badge = document.createElement('span');
    badge.className = 'status-badge badge-queued';
    badge.textContent = data.status_label || 'Queued';
    badge.dataset.role = 'status-badge';
    tdStatus.appendChild(badge);
    tr.appendChild(tdStatus);

    // Column 4: progress bar
    const tdProgress = document.createElement('td');
    const progressWrap = document.createElement('div');
    progressWrap.className = 'progress-wrap';
    const progressBar = document.createElement('div');
    progressBar.className = 'progress-bar';
    progressBar.dataset.role = 'progress-bar';
    progressBar.style.width = `${data.progress || 0}%`;
    progressWrap.appendChild(progressBar);
    tdProgress.appendChild(progressWrap);
    tr.appendChild(tdProgress);

    tbody.appendChild(tr);

    // Right-click context menu
    tr.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        showContextMenu(e.clientX, e.clientY, experiment_id);
    });
}

function removeBrowserTableRow(experiment_id) {
    const row = document.getElementById(rowId(experiment_id));
    if (row) row.remove();
}

function updateStatusBadge(experiment_id, labelText, badgeClass) {
    const row = document.getElementById(rowId(experiment_id));
    if (!row) return;
    const badge = row.querySelector('[data-role="status-badge"]');
    if (!badge) return;
    badge.textContent = labelText;
    badge.className = `status-badge ${badgeClass}`;
}

function updateProgressBar(experiment_id, value) {
    const row = document.getElementById(rowId(experiment_id));
    if (!row) return;
    const bar = row.querySelector('[data-role="progress-bar"]');
    if (!bar) return;
    bar.style.width = `${Math.min(100, Math.max(0, value))}%`;
}

function enableResumeButton(experiment_id) {
    // The abort/resume button is global (single experiment running at a time).
    // If this experiment is the most recent, update the global button.
    const btn = document.getElementById('abort-btn');
    if (btn) {
        btn.textContent = 'Resume';
        btn.dataset.resumeExperimentId = experiment_id;
    }
}

// ---------------------------------------------------------------------------
// Context menu
// ---------------------------------------------------------------------------

let _contextMenu = null;

function getOrCreateContextMenu() {
    if (_contextMenu) return _contextMenu;
    const menu = document.createElement('ul');
    menu.id = 'context-menu';
    menu.className = 'context-menu';
    menu.style.display = 'none';
    document.body.appendChild(menu);
    // Use mousedown (not click) so it doesn't fire on the same right-click
    // that opened the menu, and use capture so it fires before other handlers.
    document.addEventListener('mousedown', (e) => {
        if (_contextMenu && !_contextMenu.contains(e.target)) {
            hideContextMenu();
        }
    }, true);
    _contextMenu = menu;
    return menu;
}

function hideContextMenu() {
    const menu = document.getElementById('context-menu');
    if (menu) menu.style.display = 'none';
}

function showContextMenu(x, y, experiment_id) {
    const menu = getOrCreateContextMenu();
    menu.innerHTML = '';

    const items = [
        {
            label: 'Use These Parameters',
            action: () => useParameters(experiment_id),
        },
        {
            label: 'Remove',
            action: () => removeExperiment(experiment_id),
        },
        {
            label: 'Open File',
            action: () => openFile(experiment_id),
        },
    ];

    items.forEach(({ label, action }) => {
        const li = document.createElement('li');
        li.textContent = label;
        li.addEventListener('click', () => {
            hideContextMenu();
            action();
        });
        menu.appendChild(li);
    });

    menu.style.left = `${x}px`;
    menu.style.top = `${y}px`;
    menu.style.display = 'block';
}

function useParameters(experiment_id) {
    const exp = experiments.get(experiment_id);
    if (!exp || !exp.params) return;
    const form = document.getElementById('params-form');
    if (!form) return;
    Object.entries(exp.params).forEach(([key, value]) => {
        const input = form.querySelector(`[name="${CSS.escape(key)}"]`);
        if (input) input.value = value;
    });
}

function removeExperiment(experiment_id) {
    const exp = experiments.get(experiment_id);
    if (!exp) return;
    if (!confirm(`Remove experiment "${exp.filename}"?`)) return;
    fetch('/remove', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ experiment_id }),
    }).catch(console.error);
}

function openFile(experiment_id) {
    const exp = experiments.get(experiment_id);
    if (!exp) return;
    fetch('/open_file', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filepath: exp.filepath }),
    }).catch(console.error);
}

// ---------------------------------------------------------------------------
// Bokeh plot helpers
// ---------------------------------------------------------------------------

function setCurveVisible(experiment_id, visible) {
    if (typeof window.bokehSources === 'undefined') return;
    const source = window.bokehSources[experiment_id];
    if (!source) return;
    // The glyph renderer visibility is expected to be stored on
    // window.bokehRenderers[experiment_id] by the template glue code.
    if (window.bokehRenderers && window.bokehRenderers[experiment_id]) {
        window.bokehRenderers[experiment_id].visible = visible;
    }
}

function removeCurveFromPlot(experiment_id) {
    if (typeof window.removeCurveFromPlot === 'function') {
        window.removeCurveFromPlot(experiment_id);
    }
}

function updatePlot(experiment_id, xs, ys) {
    if (typeof window.bokehSources === 'undefined') return;
    const source = window.bokehSources[experiment_id];
    if (!source) return;
    source.data = { x: xs, y: ys };
    source.change.emit();
}

function streamToPlot(experiment_id, newXs, newYs) {
    if (typeof window.bokehSources === 'undefined') return;
    const source = window.bokehSources[experiment_id];
    if (!source) return;
    if (newXs.length === 0) return;
    source.stream({ x: newXs, y: newYs });
}

// ---------------------------------------------------------------------------
// Data polling
// ---------------------------------------------------------------------------

function fetchData(experiment_id, fullReload = false) {
    const state = plotSources[experiment_id];
    if (!state) return;

    const after = fullReload ? 0 : state.lastCount;
    const xAxis = document.getElementById('x-axis-select')
        ? document.getElementById('x-axis-select').value
        : '';
    const yAxis = document.getElementById('y-axis-select')
        ? document.getElementById('y-axis-select').value
        : '';

    let url = `/data/${encodeURIComponent(experiment_id)}?after=${after}`;
    if (xAxis) url += `&x=${encodeURIComponent(xAxis)}`;
    if (yAxis) url += `&y=${encodeURIComponent(yAxis)}`;

    fetch(url)
        .then((res) => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            return res.json();
        })
        .then(({ xs, ys, total }) => {
            if (!plotSources[experiment_id]) return; // removed while fetching
            if (fullReload || after === 0) {
                // Full data replace
                const allXs = (state.xs || []).concat(xs || []);
                const allYs = (state.ys || []).concat(ys || []);
                plotSources[experiment_id].xs = fullReload ? (xs || []) : allXs;
                plotSources[experiment_id].ys = fullReload ? (ys || []) : allYs;
                plotSources[experiment_id].lastCount = total || (xs ? xs.length : 0);
                updatePlot(experiment_id,
                    plotSources[experiment_id].xs,
                    plotSources[experiment_id].ys);
            } else {
                // Incremental stream
                if (xs && xs.length > 0) {
                    state.xs = state.xs.concat(xs);
                    state.ys = state.ys.concat(ys);
                    state.lastCount = total || state.lastCount + xs.length;
                    streamToPlot(experiment_id, xs, ys);
                }
            }
        })
        .catch((err) => console.error(`fetchData(${experiment_id}):`, err));
}

function startPolling(experiment_id) {
    stopPolling(experiment_id); // clear any existing
    const id = setInterval(() => fetchData(experiment_id, false), 200);
    pollingIntervals.set(experiment_id, id);
}

function stopPolling(experiment_id) {
    if (pollingIntervals.has(experiment_id)) {
        clearInterval(pollingIntervals.get(experiment_id));
        pollingIntervals.delete(experiment_id);
    }
}

// ---------------------------------------------------------------------------
// Queue button
// ---------------------------------------------------------------------------

function initQueueButton() {
    const btn = document.getElementById('queue-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        const form = document.getElementById('params-form');
        const directoryInput = document.getElementById('directory-input');
        if (!form) return;

        const params = {};
        form.querySelectorAll('[name]').forEach((input) => {
            params[input.name] = input.value;
        });
        const directory = directoryInput ? directoryInput.value : '';

        fetch('/queue', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params, directory }),
        })
            .then((res) => {
                if (!res.ok) return res.json().then((d) => Promise.reject(d));
                btn.disabled = true;
                setTimeout(() => { btn.disabled = false; }, 1000);
            })
            .catch((err) => {
                const msg = (err && err.message) ? err.message : JSON.stringify(err);
                alert(`Queue error: ${msg}`);
            });
    });
}

// ---------------------------------------------------------------------------
// Abort / Resume button
// ---------------------------------------------------------------------------

function initAbortResumeButton() {
    const btn = document.getElementById('abort-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        const isAbort = btn.textContent.trim() === 'Abort';
        const url = isAbort ? '/abort' : '/resume';
        fetch(url, { method: 'POST' })
            .then((res) => {
                if (!res.ok) throw new Error(`HTTP ${res.status}`);
                btn.textContent = isAbort ? 'Resume' : 'Abort';
            })
            .catch((err) => {
                alert(`${isAbort ? 'Abort' : 'Resume'} error: ${err.message}`);
            });
    });
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

function initTabs() {
    document.querySelectorAll('.tab-btn').forEach((btn) => {
        btn.addEventListener('click', () => {
            const target = btn.dataset.tab;
            document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach((c) => c.classList.remove('active'));
            btn.classList.add('active');
            const content = document.querySelector(`.tab-content[data-tab="${target}"]`);
            if (content) content.classList.add('active');
            // Trigger Bokeh resize when plot tab becomes visible
            if (target === 'plot') {
                setTimeout(() => window.dispatchEvent(new Event('resize')), 50);
            }
        });
    });
}

// ---------------------------------------------------------------------------
// X/Y axis selection
// ---------------------------------------------------------------------------

function initAxisSelects() {
    const xSel = document.getElementById('x-axis-select');
    const ySel = document.getElementById('y-axis-select');
    if (!xSel || !ySel) return;

    function onAxisChange() {
        const x_axis = xSel.value;
        const y_axis = ySel.value;
        fetch('/set_axes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x_axis, y_axis }),
        }).catch(console.error);

        // Re-fetch full data for all experiments and reload their sources
        experiments.forEach((_, experiment_id) => {
            if (plotSources[experiment_id]) {
                plotSources[experiment_id].lastCount = 0;
                plotSources[experiment_id].xs = [];
                plotSources[experiment_id].ys = [];
            }
            fetchData(experiment_id, true);
        });
    }

    xSel.addEventListener('change', onAxisChange);
    ySel.addEventListener('change', onAxisChange);
}

// ---------------------------------------------------------------------------
// Sequencer
// ---------------------------------------------------------------------------

/**
 * Each row in the sequencer table is represented as:
 *   { depth: number, parameter: string, sequence: string, rowEl: <tr> }
 *
 * Children are rows that immediately follow a parent in the flat list and have
 * depth === parent.depth + 1.
 */

let seqRows = []; // ordered flat list of sequencer row descriptors

function initSequencer() {
    const addRootBtn = document.getElementById('add-root-btn');
    const loadSeqBtn = document.getElementById('load-seq-btn');
    const seqFileInput = document.getElementById('seq-file-input');
    const queueSeqBtn = document.getElementById('queue-seq-btn');
    const directoryInput = document.getElementById('directory-input');

    if (addRootBtn) {
        addRootBtn.addEventListener('click', () => {
            addSeqRow(0, seqRows.length);
        });
    }

    if (loadSeqBtn && seqFileInput) {
        loadSeqBtn.addEventListener('click', () => seqFileInput.click());
        seqFileInput.addEventListener('change', () => {
            const file = seqFileInput.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = (e) => {
                const content = e.target.result;
                fetch('/parse_sequence', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content }),
                })
                    .then((res) => {
                        if (!res.ok) throw new Error(`HTTP ${res.status}`);
                        return res.json();
                    })
                    .then((tree) => {
                        renderSeqTree(tree);
                    })
                    .catch((err) => alert(`Load sequence error: ${err.message}`));
            };
            reader.readAsText(file);
            seqFileInput.value = '';
        });
    }

    if (queueSeqBtn) {
        queueSeqBtn.addEventListener('click', () => {
            const tree = seqRowsToTree();
            const directory = directoryInput ? directoryInput.value : '';
            const count = countTreeExperiments(tree);
            const statusEl = document.getElementById('seq-status');
            if (statusEl) {
                statusEl.textContent = `Queuing ${count} experiments...`;
                setTimeout(() => { statusEl.textContent = ''; }, 3000);
            }
            fetch('/queue_sequence', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tree, directory }),
            }).catch((err) => alert(`Queue sequence error: ${err.message}`));
        });
    }
}

function getParamNames() {
    return (window.paramNames && window.paramNames.length) ? window.paramNames : [];
}

function buildParamSelect(selectedValue) {
    const sel = document.createElement('select');
    sel.className = 'seq-param-select';
    const paramNames = getParamNames();
    paramNames.forEach((name) => {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        if (name === selectedValue) opt.selected = true;
        sel.appendChild(opt);
    });
    return sel;
}

function addSeqRow(depth, insertAfterIndex, paramValue, seqValue) {
    const tbody = document.querySelector('#seq-table tbody');
    if (!tbody) return;

    const tr = document.createElement('tr');
    tr.className = 'seq-row';
    tr.dataset.depth = depth;

    // Depth cell
    const tdDepth = document.createElement('td');
    tdDepth.className = 'seq-depth-cell';
    tdDepth.style.paddingLeft = `${depth * 20 + 4}px`;
    tdDepth.textContent = depth;
    tr.appendChild(tdDepth);

    // Parameter select
    const tdParam = document.createElement('td');
    const paramSel = buildParamSelect(paramValue || '');
    tdParam.appendChild(paramSel);
    tr.appendChild(tdParam);

    // Sequence string
    const tdSeq = document.createElement('td');
    const seqInput = document.createElement('input');
    seqInput.type = 'text';
    seqInput.className = 'seq-input';
    seqInput.placeholder = 'e.g. 1, 2, 3  or  linspace(0,10,5)';
    if (seqValue !== undefined) seqInput.value = seqValue;
    tdSeq.appendChild(seqInput);
    tr.appendChild(tdSeq);

    // +Child button
    const tdAddChild = document.createElement('td');
    const addChildBtn = document.createElement('button');
    addChildBtn.textContent = '+Child';
    addChildBtn.className = 'seq-btn';
    addChildBtn.addEventListener('click', () => {
        const idx = seqRows.findIndex((r) => r.rowEl === tr);
        if (idx === -1) return;
        // Insert after the last child of this row
        const insertIdx = findLastDescendantIndex(idx) + 1;
        addSeqRow(depth + 1, insertIdx);
    });
    tdAddChild.appendChild(addChildBtn);
    tr.appendChild(tdAddChild);

    // Remove button
    const tdRemove = document.createElement('td');
    const removeBtn = document.createElement('button');
    removeBtn.textContent = 'Remove';
    removeBtn.className = 'seq-btn seq-btn-remove';
    removeBtn.addEventListener('click', () => {
        const idx = seqRows.findIndex((r) => r.rowEl === tr);
        if (idx === -1) return;
        removeSeqRowAndChildren(idx);
    });
    tdRemove.appendChild(removeBtn);
    tr.appendChild(tdRemove);

    // Insert into DOM
    const descriptor = { depth, rowEl: tr, paramSel, seqInput };

    if (insertAfterIndex >= seqRows.length) {
        tbody.appendChild(tr);
        seqRows.push(descriptor);
    } else {
        // Insert after last descendant of the row at insertAfterIndex - 1
        const refDescriptor = seqRows[insertAfterIndex];
        tbody.insertBefore(tr, refDescriptor.rowEl);
        seqRows.splice(insertAfterIndex, 0, descriptor);
    }
}

function findLastDescendantIndex(idx) {
    const parentDepth = seqRows[idx].depth;
    let last = idx;
    for (let i = idx + 1; i < seqRows.length; i++) {
        if (seqRows[i].depth > parentDepth) last = i;
        else break;
    }
    return last;
}

function removeSeqRowAndChildren(idx) {
    const parentDepth = seqRows[idx].depth;
    let count = 1;
    for (let i = idx + 1; i < seqRows.length; i++) {
        if (seqRows[i].depth > parentDepth) count++;
        else break;
    }
    for (let i = idx; i < idx + count; i++) {
        seqRows[i].rowEl.remove();
    }
    seqRows.splice(idx, count);
}

function seqRowsToTree() {
    // Build a recursive tree from the flat seqRows list
    function buildChildren(startIdx, parentDepth) {
        const nodes = [];
        let i = startIdx;
        while (i < seqRows.length) {
            const row = seqRows[i];
            if (row.depth !== parentDepth) break;
            const node = {
                parameter: row.paramSel.value,
                sequence: row.seqInput.value,
                children: [],
            };
            // Collect children at depth + 1
            const childStart = i + 1;
            const childNodes = buildChildren(childStart, parentDepth + 1);
            node.children = childNodes.nodes;
            i = childNodes.nextIdx;
            nodes.push(node);
        }
        return { nodes, nextIdx: i };
    }
    return buildChildren(0, 0).nodes;
}

function countTreeExperiments(tree) {
    if (!tree || tree.length === 0) return 0;
    let total = 0;
    tree.forEach((node) => {
        const seqLen = estimateSequenceLength(node.sequence);
        const childCount = countTreeExperiments(node.children);
        total += seqLen * Math.max(1, childCount);
    });
    return total || 1;
}

function estimateSequenceLength(seqStr) {
    if (!seqStr) return 1;
    // Count comma-separated values as a rough estimate
    return seqStr.split(',').filter((s) => s.trim() !== '').length || 1;
}

function renderSeqTree(tree) {
    // Clear existing rows
    const tbody = document.querySelector('#seq-table tbody');
    if (tbody) tbody.innerHTML = '';
    seqRows = [];

    function insertNode(node, depth) {
        const idx = seqRows.length;
        addSeqRow(depth, idx, node.parameter, node.sequence);
        (node.children || []).forEach((child) => insertNode(child, depth + 1));
    }

    (tree || []).forEach((node) => insertNode(node, 0));
}

// ---------------------------------------------------------------------------
// DOMContentLoaded — wire everything up
// ---------------------------------------------------------------------------

function initHideAllButton() {
    const btn = document.getElementById('hide-all-btn');
    if (!btn) return;
    btn.addEventListener('click', () => {
        document.querySelectorAll('#browser-table tbody input[type="checkbox"]').forEach((cb) => {
            if (cb.checked) {
                cb.checked = false;
                cb.dispatchEvent(new Event('change'));
            }
        });
    });
}

document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initQueueButton();
    initAbortResumeButton();
    initAxisSelects();
    initSequencer();
    initHideAllButton();

    // Ensure bokehSources and bokehRenderers exist for the glue code
    if (typeof window.bokehSources === 'undefined') window.bokehSources = {};
    if (typeof window.bokehRenderers === 'undefined') window.bokehRenderers = {};
    if (typeof window.paramNames === 'undefined') window.paramNames = [];
});
