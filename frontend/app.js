/**
 * app.js — VoiceGuard Frontend Application
 *
 * Handles:
 *   - WebSocket connection management
 *   - Real-time risk gauge rendering (Canvas arc)
 *   - Chart.js risk timeline
 *   - Live session (microphone via WebSocket)
 *   - File upload analysis
 *   - Speaker enrollment & listing
 *   - Alert history & threshold management
 *   - Toast notifications
 */

'use strict';

// ── Configuration ─────────────────────────────────────────────────────────────
const API_BASE = '';  // Same origin
// Derive WebSocket scheme from page protocol to support both HTTP and HTTPS deployments.
// ws:// for HTTP, wss:// for HTTPS — prevents mixed-content errors under TLS.
const WS_SCHEME = location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${WS_SCHEME}//${location.host}/ws/stream`;

// ── State ─────────────────────────────────────────────────────────────────────
let ws = null;
let wsConnected = false;
let liveSessionActive = false;
let audioContext = null;
let audioSource = null;
let audioProcessor = null;
let mediaStream = null;
let chunkCount = 0;
let peakRisk = 0;
let riskSum = 0;
let timelineData = { labels: [], datasets: [] };
let riskTimelineChart = null;
let selectedAnalyzeFile = null;
let enrollFiles = [];
let currentAlertLevel = 'SAFE';

// ── Gauge Drawing ─────────────────────────────────────────────────────────────
const gaugeCanvas = document.getElementById('gaugeCanvas');
const gaugeCtx = gaugeCanvas.getContext('2d');

const RISK_COLORS = {
  SAFE: '#22c55e',
  LOW: '#f59e0b',
  MEDIUM: '#f97316',
  HIGH: '#ef4444',
  CRITICAL: '#dc2626',
};

function getRiskColor(score) {
  if (score >= 0.95) return RISK_COLORS.CRITICAL;
  if (score >= 0.80) return RISK_COLORS.HIGH;
  if (score >= 0.60) return RISK_COLORS.MEDIUM;
  if (score >= 0.35) return RISK_COLORS.LOW;
  return RISK_COLORS.SAFE;
}

function getRiskLevel(score) {
  if (score >= 0.95) return 'CRITICAL';
  if (score >= 0.80) return 'HIGH';
  if (score >= 0.60) return 'MEDIUM';
  if (score >= 0.35) return 'LOW';
  return 'SAFE';
}

function drawGauge(score) {
  const w = gaugeCanvas.width;
  const h = gaugeCanvas.height;
  const cx = w / 2;
  const cy = h - 20;
  const r = 110;
  const startAngle = Math.PI;
  const endAngle = 2 * Math.PI;
  const sweepAngle = (endAngle - startAngle) * score;

  gaugeCtx.clearRect(0, 0, w, h);

  // Background track
  gaugeCtx.beginPath();
  gaugeCtx.arc(cx, cy, r, startAngle, endAngle);
  gaugeCtx.strokeStyle = 'rgba(255,255,255,0.05)';
  gaugeCtx.lineWidth = 18;
  gaugeCtx.lineCap = 'round';
  gaugeCtx.stroke();

  // Risk segments (color gradient)
  const segments = [
    { from: 0.00, to: 0.35, color: '#22c55e' },
    { from: 0.35, to: 0.60, color: '#f59e0b' },
    { from: 0.60, to: 0.80, color: '#f97316' },
    { from: 0.80, to: 0.95, color: '#ef4444' },
    { from: 0.95, to: 1.00, color: '#dc2626' },
  ];

  segments.forEach(seg => {
    const sa = startAngle + (endAngle - startAngle) * seg.from;
    const ea = startAngle + (endAngle - startAngle) * Math.min(seg.to, score);
    if (ea <= sa) return;
    gaugeCtx.beginPath();
    gaugeCtx.arc(cx, cy, r, sa, ea);
    gaugeCtx.strokeStyle = seg.color;
    gaugeCtx.lineWidth = 18;
    gaugeCtx.lineCap = 'round';
    gaugeCtx.stroke();
  });

  // Needle
  const needleAngle = startAngle + sweepAngle;
  const needleLen = r - 12;
  const nx = cx + needleLen * Math.cos(needleAngle);
  const ny = cy + needleLen * Math.sin(needleAngle);
  gaugeCtx.beginPath();
  gaugeCtx.moveTo(cx, cy);
  gaugeCtx.lineTo(nx, ny);
  gaugeCtx.strokeStyle = getRiskColor(score);
  gaugeCtx.lineWidth = 3;
  gaugeCtx.lineCap = 'round';
  gaugeCtx.shadowBlur = 8;
  gaugeCtx.shadowColor = getRiskColor(score);
  gaugeCtx.stroke();
  gaugeCtx.shadowBlur = 0;

  // Center dot
  gaugeCtx.beginPath();
  gaugeCtx.arc(cx, cy, 7, 0, 2 * Math.PI);
  gaugeCtx.fillStyle = getRiskColor(score);
  gaugeCtx.fill();

  // Tick marks
  for (let i = 0; i <= 10; i++) {
    const a = startAngle + (endAngle - startAngle) * (i / 10);
    const inner = r - 26;
    const outer = r - 20;
    gaugeCtx.beginPath();
    gaugeCtx.moveTo(cx + inner * Math.cos(a), cy + inner * Math.sin(a));
    gaugeCtx.lineTo(cx + outer * Math.cos(a), cy + outer * Math.sin(a));
    gaugeCtx.strokeStyle = 'rgba(255,255,255,0.15)';
    gaugeCtx.lineWidth = 1.5;
    gaugeCtx.stroke();
  }

  // Labels
  gaugeCtx.fillStyle = 'rgba(148,163,184,0.7)';
  gaugeCtx.font = '10px Inter';
  gaugeCtx.textAlign = 'center';
  gaugeCtx.fillText('0', cx + (r + 16) * Math.cos(startAngle), cy + 4);
  gaugeCtx.fillText('1', cx + (r + 16) * Math.cos(endAngle), cy + 4);
  gaugeCtx.fillText('0.5', cx, cy - r - 10);

  // Update DOM
  document.getElementById('gauge-value').textContent = score.toFixed(2);
  const level = getRiskLevel(score);
  const levelEl = document.getElementById('gauge-label');
  levelEl.textContent = level;
  levelEl.style.color = getRiskColor(score);
}

// ── Risk Timeline Chart ───────────────────────────────────────────────────────
function initTimeline() {
  const ctx = document.getElementById('riskTimeline').getContext('2d');
  riskTimelineChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: [],
      datasets: [{
        label: 'Risk Score',
        data: [],
        borderColor: '#6366f1',
        backgroundColor: 'rgba(99,102,241,0.07)',
        borderWidth: 2,
        pointRadius: 3,
        pointBackgroundColor: '#6366f1',
        tension: 0.4,
        fill: true,
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: '#475569', font: { family: 'JetBrains Mono', size: 10 } },
          grid: { color: 'rgba(255,255,255,0.03)' },
        },
        y: {
          min: 0, max: 1,
          ticks: { color: '#475569', font: { family: 'JetBrains Mono', size: 10 } },
          grid: { color: 'rgba(255,255,255,0.04)' },
        }
      },
      animation: { duration: 200 },
    }
  });
}

function addTimelinePoint(chunk_id, risk) {
  const chart = riskTimelineChart;
  if (!chart) return;
  chart.data.labels.push(`#${chunk_id}`);
  chart.data.datasets[0].data.push(risk);
  // Dynamic color
  chart.data.datasets[0].borderColor = getRiskColor(risk);
  chart.data.datasets[0].pointBackgroundColor = getRiskColor(risk);
  if (chart.data.labels.length > 60) {
    chart.data.labels.shift();
    chart.data.datasets[0].data.shift();
  }
  chart.update('none');
}

function clearTimeline() {
  if (!riskTimelineChart) return;
  riskTimelineChart.data.labels = [];
  riskTimelineChart.data.datasets[0].data = [];
  riskTimelineChart.update();
  chunkCount = 0; peakRisk = 0; riskSum = 0;
  drawGauge(0);
  updateStatDisplay(0, 0, 0, null);
}

// ── Alert Display ─────────────────────────────────────────────────────────────
function updateAlertDisplay(level, recommendation) {
  const iconWrap = document.getElementById('alert-icon-wrap');
  const title = document.getElementById('alert-title');
  const message = document.getElementById('alert-message');
  const actions = document.getElementById('alert-actions');

  const levelClass = level.toLowerCase();
  iconWrap.className = `alert-icon-wrap ${levelClass}`;

  const icons = {
    SAFE: '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>',
    LOW: '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    MEDIUM: '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    HIGH: '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="8"/><line x1="12" y1="12" x2="12" y2="16"/></svg>',
    CRITICAL: '<svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  };

  iconWrap.innerHTML = icons[level] || icons.SAFE;

  if (recommendation) {
    title.textContent = recommendation.title || level;
    message.textContent = recommendation.message || '';

    actions.innerHTML = '';
    if (recommendation.actions && recommendation.actions.length > 0) {
      recommendation.actions.forEach(action => {
        const div = document.createElement('div');
        div.className = 'action-item';
        div.textContent = action;
        actions.appendChild(div);
      });
    }
  }
}

// ── Stat Display ──────────────────────────────────────────────────────────────
function updateStatDisplay(peak, mean, count, latency) {
  document.getElementById('peak-risk').textContent = (peak || 0).toFixed(3);
  document.getElementById('mean-risk').textContent = (mean || 0).toFixed(3);
  document.getElementById('chunk-count').textContent = count || 0;
  document.getElementById('latency').textContent = latency ? `${latency.toFixed(0)}ms` : '—';
}

// ── Speaker Consistency Display ───────────────────────────────────────────────
function updateConsistencyDisplay(similarity) {
  const bar = document.getElementById('identity-bar');
  const pct = document.getElementById('identity-pct');
  const status = document.getElementById('identity-status');

  if (similarity === null || similarity === undefined) {
    bar.style.width = '0%';
    pct.textContent = '—';
    status.textContent = 'No enrolled speaker';
    return;
  }

  const pctVal = Math.max(0, Math.min(100, similarity * 100));
  bar.style.width = `${pctVal}%`;
  pct.textContent = `${pctVal.toFixed(1)}%`;

  if (similarity >= 0.75) {
    status.textContent = '✓ Speaker identity consistent';
    status.style.color = 'var(--risk-safe)';
    bar.style.background = 'linear-gradient(90deg, #22c55e, #16a34a)';
  } else if (similarity >= 0.50) {
    status.textContent = '⚠ Partial identity match';
    status.style.color = 'var(--risk-low)';
    bar.style.background = 'linear-gradient(90deg, #f59e0b, #d97706)';
  } else {
    status.textContent = '✗ Speaker identity mismatch!';
    status.style.color = 'var(--risk-high)';
    bar.style.background = 'linear-gradient(90deg, #ef4444, #dc2626)';
  }
}

// ── Log to console panel ──────────────────────────────────────────────────────
function addLog(msg, type = 'info') {
  const log = document.getElementById('ws-log');
  const entry = document.createElement('div');
  entry.className = `log-entry ${type}`;
  const time = new Date().toLocaleTimeString();
  entry.textContent = `[${time}] ${msg}`;
  log.appendChild(entry);
  log.scrollTop = log.scrollHeight;
}

// ── WebSocket Message Handler ─────────────────────────────────────────────────
function handleWsMessage(data) {
  if (data.type === 'session_start') {
    document.getElementById('session-label').textContent = `Session: ${data.session_id}`;
    addLog(`Session started: ${data.session_id}`, 'success');
    return;
  }

  if (data.type !== 'risk_update') return;

  const risk = data.risk_score;
  const level = data.alert_level;
  const chunk = data.chunk_id;
  const det = data.detection_score;
  const sim = data.speaker_similarity;

  // Gauge
  drawGauge(risk);

  // Stats
  chunkCount++;
  peakRisk = Math.max(peakRisk, risk);
  riskSum += risk;
  updateStatDisplay(peakRisk, riskSum / chunkCount, chunkCount, null);

  // Timeline
  addTimelinePoint(chunk, risk);

  // Alert display
  if (data.recommendation) {
    updateAlertDisplay(level, data.recommendation);
  }

  // Speaker consistency
  updateConsistencyDisplay(sim);

  // Feature pill availability is managed by checkSystemStatus() based on
  // actual server-reported wav2vec2_available / ecapa_available flags.
  // Do NOT activate pills unconditionally here — that would hide real status.

  // Log
  addLog(
    `Chunk #${chunk} | Risk: ${risk.toFixed(3)} | Level: ${level} | Det: ${det.toFixed(3)}`,
    (level === 'CRITICAL' || level === 'HIGH') ? 'error' : level === 'MEDIUM' ? 'warn' : 'info'
  );

  // Toast on escalation
  if (level !== currentAlertLevel) {
    if (['MEDIUM', 'HIGH', 'CRITICAL'].includes(level)) {
      showToast(
        level === 'CRITICAL' ? '🔴 CRITICAL — Confirmed Voice Cloning Attack!' :
          level === 'HIGH' ? '🚨 HIGH RISK — Voice cloning likely detected!' : '⚠️ MEDIUM RISK — Possible voice cloning',
        (level === 'CRITICAL' || level === 'HIGH') ? 'error' : 'warning',
        5000,
      );
    }
    currentAlertLevel = level;
  }
}

// ── Live Session ──────────────────────────────────────────────────────────────
async function startLiveSession() {
  if (liveSessionActive) return;

  // Request mic permission (Raw unfiltered audio is critical for detecting subtle vocoder artifacts)
  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        sampleRate: 16000,
        channelCount: 1,
        echoCancellation: false,
        noiseSuppression: false,
        autoGainControl: false
      },
      video: false
    });
  } catch (err) {
    showToast('Microphone access denied: ' + err.message, 'error');
    addLog('Microphone access denied: ' + err.message, 'error');
    return;
  }

  // Connect WebSocket
  ws = new WebSocket(WS_URL);
  ws.binaryType = 'arraybuffer';

  ws.onopen = () => {
    wsConnected = true;
    updateSystemStatus('online');
    addLog('WebSocket connected to VoiceGuard server', 'success');

    // Send speaker selection if chosen
    const speakerId = document.getElementById('live-speaker-id').value;
    if (speakerId) {
      ws.send(JSON.stringify({ type: 'enroll_speaker', speaker_id: speakerId }));
      addLog(`Speaker profile selected: ${speakerId}`, 'info');
    }

    // Start audio capture
    audioContext = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
    audioSource = audioContext.createMediaStreamSource(mediaStream);
    audioProcessor = audioContext.createScriptProcessor(4096, 1, 1);

    audioProcessor.onaudioprocess = (e) => {
      if (!wsConnected || ws.readyState !== WebSocket.OPEN) return;
      const float32 = e.inputBuffer.getChannelData(0);
      // Convert float32 → int16 for server
      const int16 = new Int16Array(float32.length);
      for (let i = 0; i < float32.length; i++) {
        int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
      }
      ws.send(int16.buffer);
    };

    audioSource.connect(audioProcessor);
    // NOTE: audioProcessor is intentionally NOT connected to audioContext.destination.
    // Connecting it to the destination would feed microphone audio directly to the
    // speakers, causing an echo / feedback loop. The processor only captures audio
    // data via onaudioprocess and sends it over the WebSocket.
  };

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      handleWsMessage(data);
    } catch (err) {
      console.warn('WS parse error:', err);
    }
  };

  ws.onerror = () => {
    addLog('WebSocket error occurred', 'error');
    updateSystemStatus('error');
  };

  ws.onclose = () => {
    wsConnected = false;
    addLog('WebSocket disconnected', 'warn');
    updateSystemStatus('offline');
    stopLiveSession();
  };

  liveSessionActive = true;
  document.getElementById('start-live-btn').classList.add('hidden');
  document.getElementById('stop-live-btn').classList.remove('hidden');
  document.getElementById('live-indicator').classList.remove('hidden');
  addLog('Live analysis session started', 'success');
}

function stopLiveSession() {
  if (!liveSessionActive) return;
  liveSessionActive = false;

  // Stop audio
  if (audioProcessor) { audioProcessor.disconnect(); audioProcessor = null; }
  if (audioSource) { audioSource.disconnect(); audioSource = null; }
  if (audioContext) { audioContext.close(); audioContext = null; }
  if (mediaStream) { mediaStream.getTracks().forEach(t => t.stop()); mediaStream = null; }

  // Close WebSocket
  if (ws && ws.readyState === WebSocket.OPEN) ws.close();
  ws = null;
  wsConnected = false;

  document.getElementById('start-live-btn').classList.remove('hidden');
  document.getElementById('stop-live-btn').classList.add('hidden');
  document.getElementById('live-indicator').classList.add('hidden');

  addLog('Live session stopped.', 'info');
  updateSystemStatus('offline');
}

// ── System Status ─────────────────────────────────────────────────────────────
function updateSystemStatus(state) {
  const statusEl = document.getElementById('system-status');
  const dot = statusEl.querySelector('.status-dot');
  const span = statusEl.querySelector('span');
  dot.className = `status-dot ${state}`;
  span.textContent = state === 'online' ? 'Connected' : state === 'error' ? 'Error' : 'Disconnected';
}

// ── Tab Navigation ────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.remove('active');
    p.classList.add('hidden');
  });
  document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));

  document.getElementById(`panel-${name}`).classList.remove('hidden');
  document.getElementById(`panel-${name}`).classList.add('active');
  document.getElementById(`tab-${name}`).classList.add('active');

  if (name === 'history') loadAlerts();
  if (name === 'enroll') loadSpeakers();
  if (name === 'analyze') populateSpeakerSelect('analyze-speaker-id');
}

// ── File Analysis ─────────────────────────────────────────────────────────────
function onDragOver(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.add('dragover');
}

function onDrop(e) {
  e.preventDefault();
  document.getElementById('upload-zone').classList.remove('dragover');
  const files = e.dataTransfer.files;
  if (files.length > 0) handleFileSelected(files[0]);
}

function onFileSelect(e) {
  if (e.target.files.length > 0) handleFileSelected(e.target.files[0]);
}

function handleFileSelected(file) {
  selectedAnalyzeFile = file;
  const sel = document.getElementById('file-selected');
  sel.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
  sel.classList.remove('hidden');
  document.getElementById('analyze-btn').disabled = false;
}

async function analyzeFile() {
  if (!selectedAnalyzeFile) return;
  const btn = document.getElementById('analyze-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Analyzing...';

  const formData = new FormData();
  formData.append('file', selectedAnalyzeFile);
  const speakerId = document.getElementById('analyze-speaker-id').value;
  if (speakerId) formData.append('speaker_id', speakerId);

  try {
    const resp = await fetch(`${API_BASE}/api/analyze`, { method: 'POST', body: formData });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    renderAnalysisResults(data);
    showToast(`Analysis complete: ${data.alert_level} (peak: ${data.peak_risk.toFixed(3)})`,
      (data.alert_level === 'CRITICAL' || data.alert_level === 'HIGH') ? 'error' : data.alert_level === 'MEDIUM' ? 'warning' : 'success');
  } catch (err) {
    showToast('Analysis failed: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg> Analyze Audio';
  }
}

function renderAnalysisResults(data) {
  const body = document.getElementById('results-body');
  const color = getRiskColor(data.peak_risk);
  const level = data.alert_level;

  body.innerHTML = `
    <div class="result-summary">
      <div class="result-stat-card">
        <div class="result-stat-value" style="color:${color}">${data.peak_risk.toFixed(3)}</div>
        <div class="result-stat-label">Peak Risk</div>
      </div>
      <div class="result-stat-card">
        <div class="result-stat-value" style="color:${getRiskColor(data.mean_risk)}">${data.mean_risk.toFixed(3)}</div>
        <div class="result-stat-label">Mean Risk</div>
      </div>
      <div class="result-stat-card">
        <div class="result-stat-value">${data.total_chunks}</div>
        <div class="result-stat-label">Chunks</div>
      </div>
    </div>

    <div style="margin-bottom:14px;padding:14px;border-radius:10px;background:${color}15;border:1px solid ${color}40">
      <div style="font-size:15px;font-weight:700;color:${color};margin-bottom:4px">${data.recommendation.title}</div>
      <div style="font-size:12px;color:#94a3b8">${data.recommendation.message}</div>
    </div>

    <div style="font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;color:#475569;margin-bottom:8px">Per-Chunk Scores</div>
    <div class="chunk-list">
      ${data.chunk_scores.map(c => `
        <div class="chunk-row">
          <span class="chunk-id">Chunk ${c.chunk_id}</span>
          <div class="chunk-bar-bg">
            <div class="chunk-bar" style="width:${c.risk_score * 100}%;background:${getRiskColor(c.risk_score)}"></div>
          </div>
          <span class="chunk-score" style="color:${getRiskColor(c.risk_score)}">${c.risk_score.toFixed(3)}</span>
          <span class="chunk-level level-${c.alert_level}">${c.alert_level}</span>
        </div>
      `).join('')}
    </div>
  `;
}

// ── Speaker Enrollment ────────────────────────────────────────────────────────
function onEnrollDrop(e) {
  e.preventDefault();
  const files = Array.from(e.dataTransfer.files);
  enrollFiles = [...enrollFiles, ...files];
  updateEnrollFileCount();
}

function onEnrollFilesSelected(e) {
  enrollFiles = Array.from(e.target.files);
  updateEnrollFileCount();
}

function updateEnrollFileCount() {
  const badge = document.getElementById('enroll-file-count');
  if (enrollFiles.length > 0) {
    badge.textContent = `${enrollFiles.length} file${enrollFiles.length > 1 ? 's' : ''} selected`;
    badge.classList.remove('hidden');
    document.getElementById('enroll-btn').disabled = false;
  } else {
    badge.classList.add('hidden');
    document.getElementById('enroll-btn').disabled = true;
  }
}

async function enrollSpeaker() {
  const name = document.getElementById('enroll-name').value.trim();
  if (!name) { showToast('Please enter a speaker name.', 'warning'); return; }
  if (enrollFiles.length === 0) { showToast('Please select audio files.', 'warning'); return; }

  const btn = document.getElementById('enroll-btn');
  btn.disabled = true;
  btn.innerHTML = '<div class="spinner"></div> Enrolling...';

  const formData = new FormData();
  formData.append('name', name);
  const org = document.getElementById('enroll-org').value.trim();
  const role = document.getElementById('enroll-role').value.trim();
  const sid = document.getElementById('enroll-id').value.trim();
  if (org) formData.append('organization', org);
  if (role) formData.append('role', role);
  if (sid) formData.append('speaker_id', sid);
  enrollFiles.forEach(f => formData.append('files', f));

  const resultEl = document.getElementById('enroll-result');

  try {
    const resp = await fetch(`${API_BASE}/api/speakers/enroll`, { method: 'POST', body: formData });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    resultEl.className = 'enroll-result success';
    resultEl.textContent = data.message;
    resultEl.classList.remove('hidden');
    showToast(`Speaker "${data.name}" enrolled successfully!`, 'success');
    loadSpeakers();
    // Reset form
    enrollFiles = [];
    updateEnrollFileCount();
    document.getElementById('enroll-name').value = '';
    document.getElementById('enroll-org').value = '';
    document.getElementById('enroll-role').value = '';
    document.getElementById('enroll-id').value = '';
  } catch (err) {
    resultEl.className = 'enroll-result error';
    resultEl.textContent = 'Enrollment failed: ' + err.message;
    resultEl.classList.remove('hidden');
    showToast('Enrollment failed: ' + err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><line x1="12" y1="3" x2="12" y2="9"/><line x1="9" y1="6" x2="15" y2="6"/></svg> Enroll Speaker';
  }
}

async function loadSpeakers() {
  const list = document.getElementById('speakers-list');
  try {
    const resp = await fetch(`${API_BASE}/api/speakers`);
    const speakers = await resp.json();
    if (!speakers.length) {
      list.innerHTML = '<div class="speakers-empty">No speakers enrolled yet.</div>';
      return;
    }

    // Build speaker items using DOM API (not innerHTML) to prevent XSS.
    // All user-supplied values (name, organization, role, speaker_id) are
    // assigned via textContent, which treats them as plain text only.
    list.innerHTML = '';
    speakers.forEach(s => {
      const item = document.createElement('div');
      item.className = 'speaker-item';
      item.id = `sp-${s.speaker_id}`;

      const avatar = document.createElement('div');
      avatar.className = 'speaker-avatar';
      avatar.textContent = (s.name || '?').charAt(0).toUpperCase();

      const info = document.createElement('div');
      info.className = 'speaker-info';

      const nameEl = document.createElement('div');
      nameEl.className = 'speaker-name';
      nameEl.textContent = s.name || '—';

      const meta = document.createElement('div');
      meta.className = 'speaker-meta';
      const parts = [];
      if (s.organization) parts.push(s.organization);
      if (s.role) parts.push(s.role);
      parts.push(`${s.num_samples} samples`);
      meta.textContent = parts.join(' · ');

      const badge = document.createElement('div');
      badge.className = 'speaker-id-badge';
      badge.textContent = s.speaker_id;

      info.appendChild(nameEl);
      info.appendChild(meta);
      info.appendChild(badge);

      // Delete button — uses closure (not inline onclick string) to safely
      // pass the speaker_id without embedding it in HTML attribute context.
      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'delete-btn';
      deleteBtn.title = 'Delete speaker';
      // Static SVG markup is trusted (not user data):
      deleteBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a1 1 0 011-1h4a1 1 0 011 1v2"/></svg>';
      deleteBtn.addEventListener('click', () => deleteSpeaker(s.speaker_id));

      item.appendChild(avatar);
      item.appendChild(info);
      item.appendChild(deleteBtn);
      list.appendChild(item);
    });
  } catch (err) {
    list.innerHTML = '<div class="speakers-empty">Error loading speakers.</div>';
  }
  populateSpeakerSelect('live-speaker-id');
  populateSpeakerSelect('analyze-speaker-id');
}

async function deleteSpeaker(speakerId) {
  if (!confirm(`Delete speaker profile "${speakerId}"? This cannot be undone.`)) return;
  try {
    await fetch(`${API_BASE}/api/speakers/${speakerId}`, { method: 'DELETE' });
    showToast('Speaker deleted.', 'success');
    loadSpeakers();
  } catch (err) {
    showToast('Delete failed: ' + err.message, 'error');
  }
}

async function populateSpeakerSelect(selectId) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const current = sel.value;
  try {
    const resp = await fetch(`${API_BASE}/api/speakers`);
    const speakers = await resp.json();
    sel.innerHTML = '<option value="">None</option>' +
      speakers.map(s => `<option value="${s.speaker_id}">${s.name} (${s.speaker_id})</option>`).join('');
    if (current) sel.value = current;
  } catch (_) { }
}

function refreshSpeakers() { populateSpeakerSelect('live-speaker-id'); }

// ── Alert History ─────────────────────────────────────────────────────────────
async function loadAlerts() {
  const wrap = document.getElementById('history-table-wrap');
  try {
    const resp = await fetch(`${API_BASE}/api/alerts/recent?limit=100`);
    const data = await resp.json();
    const alerts = data.alerts || [];
    if (!alerts.length) {
      wrap.innerHTML = '<div class="history-empty">No alerts recorded yet.</div>';
      return;
    }
    wrap.innerHTML = `
      <table class="history-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Session</th>
            <th>Risk</th>
            <th>Level</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          ${alerts.map(a => `
            <tr>
              <td>${new Date(a.timestamp * 1000).toLocaleTimeString()}</td>
              <td>${a.session_id || '—'}</td>
              <td style="color:${getRiskColor(a.risk_score)}">${(a.risk_score || 0).toFixed(3)}</td>
              <td><span class="chunk-level level-${a.alert_level}">${a.alert_level}</span></td>
              <td style="font-family:Inter;font-size:12px;color:#94a3b8">${a.recommendation_title || ''}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;
  } catch (err) {
    wrap.innerHTML = '<div class="history-empty">Error loading alert history.</div>';
  }
}

// ── Threshold Management ──────────────────────────────────────────────────────
async function updateThresholds() {
  const low = parseFloat(document.getElementById('thr-low').value);
  const medium = parseFloat(document.getElementById('thr-medium').value);
  const high = parseFloat(document.getElementById('thr-high').value);
  const resEl = document.getElementById('threshold-result');

  if (!(low < medium && medium < high)) {
    resEl.className = 'threshold-result error';
    resEl.textContent = 'Error: thresholds must satisfy LOW < MEDIUM < HIGH';
    resEl.classList.remove('hidden');
    return;
  }

  try {
    const resp = await fetch(`${API_BASE}/api/config/thresholds`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ low, medium, high }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    resEl.className = 'threshold-result success';
    resEl.textContent = `✓ Thresholds updated: LOW=${low}, MEDIUM=${medium}, HIGH=${high}`;
    resEl.classList.remove('hidden');
    showToast('Alert thresholds updated.', 'success');
  } catch (err) {
    resEl.className = 'threshold-result error';
    resEl.textContent = 'Update failed: ' + err.message;
    resEl.classList.remove('hidden');
  }
}

// ── Toast Notifications ───────────────────────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const icons = {
    success: '✅',
    error: '🚨',
    warning: '⚠️',
    info: 'ℹ️',
  };

  toast.innerHTML = `
    <span style="font-size:18px;flex-shrink:0">${icons[type] || 'ℹ️'}</span>
    <span style="flex:1;line-height:1.4">${message}</span>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;cursor:pointer;color:#94a3b8;padding:0;font-size:16px;flex-shrink:0">×</button>
  `;

  container.appendChild(toast);
  setTimeout(() => toast.remove(), duration);
}

// ── System Status Check ───────────────────────────────────────────────────────
async function checkSystemStatus() {
  try {
    const resp = await fetch(`${API_BASE}/api/config/status`);
    if (resp.ok) {
      const data = await resp.json();
      if (data.status === 'operational') {
        document.getElementById('system-status').querySelector('.status-dot').className = 'status-dot online';
        document.getElementById('system-status').querySelector('span').textContent = 'Server Online';

        // Update feature pill status
        if (data.wav2vec2_available) document.getElementById('pill-wav2vec').classList.add('active');
        if (data.ecapa_available) document.getElementById('pill-speaker').classList.add('active');

        // Load current thresholds
        if (data.config && data.config.thresholds) {
          document.getElementById('thr-low').value = data.config.thresholds.low;
          document.getElementById('thr-medium').value = data.config.thresholds.medium;
          document.getElementById('thr-high').value = data.config.thresholds.high;
        }
      }
    }
  } catch (_) {
    document.getElementById('system-status').querySelector('.status-dot').className = 'status-dot offline';
    document.getElementById('system-status').querySelector('span').textContent = 'Server Offline';
  }
}

// ── Initialization ────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  drawGauge(0);
  initTimeline();
  checkSystemStatus();
  loadSpeakers();

  // Periodic server check
  setInterval(checkSystemStatus, 15000);

  // Populate speaker selects
  populateSpeakerSelect('live-speaker-id');
  populateSpeakerSelect('analyze-speaker-id');
});
