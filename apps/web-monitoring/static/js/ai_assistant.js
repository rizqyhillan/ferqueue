/**
 * ai_assistant.js — FERQUEUE Web Monitoring
 * Multi-turn persistent chat (up to 40 messages stored / 20 sent as LLM memory),
 * typed Daily Audit summary, Multimodal Visual Audit (captured & uploaded photos),
 * and SOP & RAG Knowledge Base Manager.
 */

import { startClock, escapeHtml, toast, API_BASE_URL } from './utils.js';

const CHAT_STORAGE_KEY = 'ferqueue.ai.chat.v1';
const MAX_STORED_MESSAGES = 40;   // Ringan (~25 KB teks di localStorage)
const MAX_SENT_HISTORY = 20;      // 10 pasang tanya-jawab dikirim ke LLM

const messagesArea = document.getElementById('ai-chat-messages');
const chatForm = document.getElementById('ai-chat-form');
const userInput = document.getElementById('ai-user-input');
const casesContainer = document.getElementById('ai-cases-container');
const memoryBadge = document.getElementById('ai-memory-badge');
const contextBar = document.getElementById('ai-context-bar');
const contextChips = document.getElementById('ai-context-chips');

let isQueryInFlight = false;
let chatMessages = [];          // [{ role: 'user'|'assistant', content, title?, vehicle?, image_url?, used_vision?, used_fallback?, retrieval_mode? }]
let activeVehicle = null;       // { id_pemeriksaan, label, foto_url }
let pendingPhotoDataUrl = null; // Foto yang dilampirkan manual di kolom input
let pendingPhotoName = '';

// State Manajemen SOP
let sopFiles = [];
let currentSopFilename = '';

function formatMarkdown(text) {
  if (!text) return '';
  let formatted = escapeHtml(text);

  formatted = formatted.replace(/^### (.*$)/gim, '<h4 style="margin: 8px 0 4px; font-size: 13px; font-weight: 700; color: #0F172A;">$1</h4>');
  formatted = formatted.replace(/^## (.*$)/gim, '<h3 style="margin: 10px 0 6px; font-size: 14px; font-weight: 700; color: #0F172A;">$1</h3>');
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
  formatted = formatted.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  formatted = formatted.replace(/^\s*-\s+(.*$)/gim, '<li style="margin-left: 16px; margin-bottom: 2px;">$1</li>');
  formatted = formatted.replace(/\n/g, '<br>');

  return formatted;
}

// ------------------------------------------------------------------
// MEMORI PERCAKAPAN PERSISTEN (LOCALSTORAGE)
// ------------------------------------------------------------------
function loadStoredChat() {
  try {
    const raw = localStorage.getItem(CHAT_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.slice(-MAX_STORED_MESSAGES);
  } catch {
    return [];
  }
}

function saveStoredChat() {
  try {
    // Hindari menyimpan base64 gambar besar ke localStorage agar tetap ringan
    const compact = chatMessages.slice(-MAX_STORED_MESSAGES).map(msg => ({
      role: msg.role,
      content: String(msg.content || '').slice(0, 4000),
      title: msg.title || null,
      vehicle: msg.vehicle || null,
      image_url: msg.image_url && !String(msg.image_url).startsWith('data:') ? msg.image_url : null,
      used_vision: Boolean(msg.used_vision),
      used_fallback: Boolean(msg.used_fallback),
      retrieval_mode: msg.retrieval_mode || null,
    }));
    localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(compact));
  } catch {
    // Abaikan bila storage penuh
  }
  updateMemoryBadge();
}

function updateMemoryBadge() {
  if (!memoryBadge) return;
  memoryBadge.textContent = `Memori: ${chatMessages.length}/${MAX_STORED_MESSAGES}`;
}

function updateContextBar() {
  if (!contextBar || !contextChips) return;
  const chips = [];

  if (activeVehicle) {
    chips.push(`
      <span class="ai-context-chip">
        <span>Konteks kasus: <strong>${escapeHtml(activeVehicle.id_pemeriksaan)}</strong></span>
        <button type="button" id="btn-clear-active-vehicle" title="Lepas konteks kendaraan">&times;</button>
      </span>
    `);
  }

  if (pendingPhotoDataUrl) {
    chips.push(`
      <span class="ai-context-chip ai-context-chip--photo">
        <img src="${pendingPhotoDataUrl}" alt="Lampiran foto" />
        <span>Foto: ${escapeHtml(pendingPhotoName || 'Lampiran')}</span>
        <button type="button" id="btn-clear-pending-photo" title="Hapus lampiran foto">&times;</button>
      </span>
    `);
  }

  contextChips.innerHTML = chips.join('');
  contextBar.hidden = chips.length === 0;

  document.getElementById('btn-clear-active-vehicle')?.addEventListener('click', () => {
    activeVehicle = null;
    document.querySelectorAll('.ai-case-card').forEach(c => c.classList.remove('is-selected'));
    updateContextBar();
  });

  document.getElementById('btn-clear-pending-photo')?.addEventListener('click', () => {
    pendingPhotoDataUrl = null;
    pendingPhotoName = '';
    updateContextBar();
  });
}

// ------------------------------------------------------------------
// RENDER PESAN CHAT
// ------------------------------------------------------------------
function renderGreeting() {
  if (!messagesArea) return;
  messagesArea.innerHTML = `
    <div class="ai-msg ai-msg--assistant">
      <div class="ai-msg-avatar ai-msg-avatar--assistant">AI</div>
      <div class="ai-msg-bubble">
        <div class="ai-output-title">Halo, Petugas Operasional Gerbang FERQUEUE!</div>
        <div class="ai-output-summary">
          Saya adalah <strong>FERQUEUE AI Assistant</strong> dengan <strong>Hybrid RAG</strong>, <strong>Memori Percakapan Multi-Turn</strong>, dan <strong>Audit Visual Multimodal</strong>. Anda bisa langsung:
        </div>
        <div class="ai-rec-box">
          <div class="ai-rec-list">
            <div>• <strong>Ketik Ringkasan Audit Harian:</strong> Cukup ketik <em>"buatkan ringkasan audit harian"</em> atau <em>"berapa truk overweight hari ini?"</em> untuk membaca statistik aktual database.</div>
            <div>• <strong>Audit Visual Multimodal:</strong> Pilih kasus overweight berfoto di sebelah kiri atau klik ikon <strong>📷</strong> untuk melampirkan foto kendaraan dan memverifikasi golongannya.</div>
            <div>• <strong>Diskusi Lanjutan (Multi-Turn):</strong> Menyimpan hingga ${MAX_STORED_MESSAGES} pesan terakhir sehingga pertanyaan lanjutan tetap nyambung.</div>
            <div>• <strong>Kelola SOP &amp; RAG:</strong> Tambah, edit, atau sinkronisasi ulang dokumen SOP langsung lewat tombol <strong>Kelola SOP &amp; RAG</strong>.</div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function appendUserBubble(text, photoPreviewUrl = null) {
  if (!messagesArea) return;
  const msgDiv = document.createElement('div');
  msgDiv.className = 'ai-msg ai-msg--user';
  const photoHtml = photoPreviewUrl
    ? `<div class="ai-msg-photo-box" style="margin-bottom:6px; border-color:rgba(255,255,255,0.2);"><img src="${photoPreviewUrl}" alt="Foto lampiran" /></div>`
    : '';
  msgDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--user">OP</div>
    <div class="ai-msg-bubble">${photoHtml}<div>${escapeHtml(text)}</div></div>
  `;
  messagesArea.appendChild(msgDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;
}

function appendAssistantBubble(data) {
  if (!messagesArea) return;
  const msgDiv = document.createElement('div');
  msgDiv.className = 'ai-msg ai-msg--assistant';

  let vehicleHtml = '';
  if (data.vehicle) {
    const v = data.vehicle;
    const isOver = String(v.status || '').toLowerCase() === 'overweight';
    vehicleHtml = `
      <div class="ai-vehicle-summary-card">
        <div class="ai-vehicle-summary-title">
          <span>DATA PEMERIKSAAN KENDARAAN</span>
          <span style="font-size: 11px; padding: 2px 6px; border-radius: 4px; ${isOver ? 'background:#FEE2E2; color:#991B1B;' : 'background:#DCFCE7; color:#166534;'}">
            ${escapeHtml(v.status || 'Normal')}
          </span>
        </div>
        <div class="ai-vehicle-grid">
          <div class="ai-vehicle-item">
            <span class="ai-vehicle-key">Jenis Kendaraan:</span>
            <span class="ai-vehicle-val">${escapeHtml(v.jenis_kendaraan || 'Mobil')} (Gol. ${escapeHtml(v.golongan || 'A')})</span>
          </div>
          <div class="ai-vehicle-item">
            <span class="ai-vehicle-key">Berat Aktual:</span>
            <span class="ai-vehicle-val">${escapeHtml(v.berat_aktual_gram)} g</span>
          </div>
          <div class="ai-vehicle-item">
            <span class="ai-vehicle-key">Batas Golongan:</span>
            <span class="ai-vehicle-val">${escapeHtml(v.batas_maksimum_gram)} g</span>
          </div>
          <div class="ai-vehicle-item">
            <span class="ai-vehicle-key">Kelebihan Muatan:</span>
            <span class="ai-vehicle-val" style="${v.kelebihan_berat_gram > 0 ? 'color:#DC2626;' : ''}">+${escapeHtml(v.kelebihan_berat_gram || 0)} g (${escapeHtml(v.persentase_kelebihan || '0%')})</span>
          </div>
          <div class="ai-vehicle-item">
            <span class="ai-vehicle-key">Kategori:</span>
            <span class="ai-vehicle-val">${escapeHtml(v.kategori_overweight || '-')}</span>
          </div>
          <div class="ai-vehicle-item">
            <span class="ai-vehicle-key">Saran Pengurangan:</span>
            <span class="ai-vehicle-val" style="color:#2563EB;">Min. -${escapeHtml(v.minimal_pengurangan_gram || 0)} g</span>
          </div>
        </div>
      </div>
    `;
  }

  const photoUrl = data.image_url || data.vehicle?.foto_url || null;
  const photoHtml = photoUrl
    ? `<div class="ai-msg-photo-box"><img src="${escapeHtml(photoUrl)}" alt="Foto kendaraan yang diaudit" loading="lazy" /></div>`
    : '';

  const badges = [];
  if (data.used_vision) {
    badges.push('<span class="ai-meta-pill ai-meta-pill--vision">👁 Audit Visual Multimodal</span>');
  }
  if (data.used_fallback) {
    badges.push('<span class="ai-meta-pill ai-meta-pill--fallback">⚡ Mode Fallback Lokal</span>');
  } else if (data.retrieval_mode) {
    const modeMap = {
      vector_chromadb: 'RAG ChromaDB',
      hybrid_vector_keyword: 'Hybrid RAG',
      keyword_local: 'SOP Lokal',
    };
    badges.push(`<span class="ai-meta-pill">📚 ${escapeHtml(modeMap[data.retrieval_mode] || data.retrieval_mode)}</span>`);
  }

  const badgesHtml = badges.length ? `<div class="ai-meta-badges">${badges.join('')}</div>` : '';

  msgDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--assistant">AI</div>
    <div class="ai-msg-bubble">
      <div class="ai-output-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" style="color:#7E22CE;">
          <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>
        </svg>
        <span>${escapeHtml(data.title || 'Analisis Cerdas FERQUEUE')}</span>
      </div>
      ${photoHtml}
      ${vehicleHtml}
      <div class="ai-output-summary" style="line-height: 1.6;">${formatMarkdown(data.summary || data.content || '')}</div>
      ${badgesHtml}
    </div>
  `;

  messagesArea.appendChild(msgDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;
}

function renderAllMessages() {
  renderGreeting();
  chatMessages.forEach(msg => {
    if (msg.role === 'user') {
      appendUserBubble(msg.content, msg.image_url);
    } else {
      appendAssistantBubble(msg);
    }
  });
  updateMemoryBadge();
}

// ------------------------------------------------------------------
// KIRIM QUERY MULTI-TURN + AUDIT HARIAN + MULTIMODAL VISION
// ------------------------------------------------------------------
async function sendQuery(queryText, explicitVehicleId = '') {
  const cleanQuery = String(queryText || '').trim();
  const hasPhoto = Boolean(pendingPhotoDataUrl);
  if ((!cleanQuery && !hasPhoto && !explicitVehicleId) || isQueryInFlight) return;
  isQueryInFlight = true;

  const submitBtn = chatForm?.querySelector('button[type="submit"]');
  if (submitBtn) submitBtn.disabled = true;

  const effectiveVehicleId = explicitVehicleId || activeVehicle?.id_pemeriksaan || '';
  const photoToSend = pendingPhotoDataUrl;
  const userDisplayText = cleanQuery || 'Lakukan audit visual pada foto kendaraan terlampir.';

  // Ambil memori riwayat sebelum pesan baru ditambahkan
  const historyPayload = chatMessages.slice(-MAX_SENT_HISTORY).map(m => ({
    role: m.role,
    content: m.content,
  }));

  appendUserBubble(userDisplayText, photoToSend);
  chatMessages.push({ role: 'user', content: userDisplayText });
  if (chatMessages.length > MAX_STORED_MESSAGES) {
    chatMessages = chatMessages.slice(-MAX_STORED_MESSAGES);
  }
  saveStoredChat();

  if (userInput) userInput.value = '';
  pendingPhotoDataUrl = null;
  pendingPhotoName = '';
  updateContextBar();

  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'ai-msg ai-msg--assistant';
  loadingDiv.id = 'ai-thinking-indicator';
  loadingDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--assistant">AI</div>
    <div class="ai-msg-bubble" style="color: var(--clr-text-muted); font-style: italic;">
      <span>${photoToSend || activeVehicle?.foto_url ? 'Menjalankan Hybrid RAG + Audit Visual Multimodal...' : 'Menganalisis data operasional & basis SOP FERQUEUE...'}</span>
    </div>
  `;
  messagesArea.appendChild(loadingDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;

  try {
    const payload = {
      query: cleanQuery,
      history: historyPayload,
      include_photo: true,
    };
    if (effectiveVehicleId) payload.id_pemeriksaan = effectiveVehicleId;
    if (photoToSend) payload.image = photoToSend;

    const res = await fetch(`${API_BASE_URL}/api/ai/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    loadingDiv.remove();

    if (res.ok) {
      const result = await res.json();
      appendAssistantBubble(result);
      chatMessages.push({
        role: 'assistant',
        content: result.summary || '',
        title: result.title,
        vehicle: result.vehicle || null,
        image_url: result.image_url || result.vehicle?.foto_url || null,
        used_vision: Boolean(result.used_vision),
        used_fallback: Boolean(result.used_fallback),
        retrieval_mode: result.retrieval_mode || null,
      });
      if (chatMessages.length > MAX_STORED_MESSAGES) {
        chatMessages = chatMessages.slice(-MAX_STORED_MESSAGES);
      }
      saveStoredChat();
    } else {
      const errJson = await res.json().catch(() => ({}));
      const errMsg = errJson.message || 'Tidak dapat memproses permintaan ke server backend.';
      appendAssistantBubble({ title: 'Pemberitahuan Sistem AI', summary: errMsg });
    }
  } catch {
    loadingDiv.remove();
    appendAssistantBubble({
      title: 'Koneksi Offline',
      summary: 'Gagal terhubung ke engine AI backend. Pastikan server Flask aktif.',
    });
  } finally {
    isQueryInFlight = false;
    if (submitBtn) submitBtn.disabled = false;
  }
}

// ------------------------------------------------------------------
// DAFTAR KENDARAAN BERMASALAH (DENGAN PREVIEW FOTO)
// ------------------------------------------------------------------
async function loadProblematicVehicles() {
  if (!casesContainer) return;
  casesContainer.innerHTML = `
    <div style="font-size: 12px; color: var(--clr-text-muted); text-align: center; padding: 12px 0;">
      Memperbarui daftar kendaraan bermasalah...
    </div>
  `;

  try {
    const res = await fetch(`${API_BASE_URL}/api/kendaraan-bermasalah`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Gagal mengambil data kendaraan');
    const json = await res.json();
    const list = json.data || [];

    if (list.length === 0) {
      casesContainer.innerHTML = `
        <div style="font-size: 12px; color: var(--clr-text-muted); text-align: center; padding: 16px 8px; line-height: 1.5;">
          Belum ada kendaraan berstatus <strong>Overweight</strong> tercatat.<br>
          <span style="font-size: 11px;">Ketik <em>"ringkasan audit harian"</em> atau lampirkan foto di kolom chat untuk uji audit visual.</span>
        </div>
      `;
      return;
    }

    casesContainer.innerHTML = '';
    list.slice(0, 10).forEach(item => {
      const card = document.createElement('div');
      card.className = 'ai-case-card';
      if (activeVehicle?.id_pemeriksaan === item.id_pemeriksaan) {
        card.classList.add('is-selected');
      }
      card.dataset.id = item.id_pemeriksaan;

      const kelebihan = item.kelebihan_berat_gram || 0;
      const pct = item.persentase_kelebihan || '0%';
      const isHeavy = String(item.kategori_overweight || '').includes('Berat');
      const thumbHtml = item.foto_url
        ? `<img class="ai-case-thumb" src="${escapeHtml(item.foto_url)}" alt="Foto ${escapeHtml(item.id_pemeriksaan)}" loading="lazy" />`
        : '';
      const photoTag = item.foto_url ? '<span class="ai-case-photo-tag">📷 Siap Audit Visual</span>' : '';

      card.innerHTML = `
        <div class="ai-case-row">
          ${thumbHtml}
          <div class="ai-case-info">
            <div class="ai-case-top">
              <span class="ai-case-id">${escapeHtml(item.id_pemeriksaan)}</span>
              <span class="ai-case-badge ${isHeavy ? 'ai-case-badge--danger' : 'ai-case-badge--warning'}">
                +${escapeHtml(kelebihan)}g (${escapeHtml(pct)})
              </span>
            </div>
            <div class="ai-case-driver">${escapeHtml(item.nama_pengemudi || 'Pengemudi')} · ${escapeHtml(item.jenis_kendaraan)} (Gol. ${escapeHtml(item.golongan)})</div>
            <div class="ai-case-meta">Berat: ${escapeHtml(item.berat_aktual_gram)}g · Batas: ${escapeHtml(item.batas_maksimum_gram)}g</div>
            ${photoTag}
          </div>
        </div>
      `;

      card.addEventListener('click', () => {
        document.querySelectorAll('.ai-case-card').forEach(c => c.classList.remove('is-selected'));
        card.classList.add('is-selected');
        activeVehicle = {
          id_pemeriksaan: item.id_pemeriksaan,
          foto_url: item.foto_url || null,
        };
        updateContextBar();
        const prompt = item.foto_url
          ? `Analisis pelanggaran kendaraan ${item.id_pemeriksaan}, lakukan audit visual pada foto tangkapannya untuk verifikasi kesesuaian golongan, dan berikan langkah penanganannya di lapangan.`
          : `Analisis pelanggaran kendaraan ${item.id_pemeriksaan} dan berikan langkah penanganannya di lapangan.`;
        sendQuery(prompt, item.id_pemeriksaan);
      });

      casesContainer.appendChild(card);
    });
  } catch (err) {
    casesContainer.innerHTML = `
      <div style="font-size: 11.5px; color: #EF4444; text-align: center; padding: 12px 0;">
        Gagal memuat daftar kendaraan (${escapeHtml(err.message)}).
      </div>
    `;
  }
}

// ------------------------------------------------------------------
// MANAJEMEN SOP & RE-INDEX RAG
// ------------------------------------------------------------------
function updateRagSummaryCard(ragStatus) {
  const badge = document.getElementById('ai-rag-summary-badge');
  const text = document.getElementById('ai-rag-summary-text');
  const dlgStatus = document.getElementById('sop-dialog-status');
  if (!ragStatus) return;

  const filesCount = ragStatus.total_files ?? 0;
  const chunksCount = ragStatus.vector_chunks ?? 0;
  const ready = Boolean(ragStatus.vector_ready);

  if (badge) {
    badge.textContent = ready ? `${chunksCount} chunks · ChromaDB` : `${filesCount} SOP · Hybrid Lokal`;
    badge.classList.toggle('is-local', !ready);
  }
  if (text) {
    text.textContent = ready
      ? `${filesCount} dokumen SOP terindeks di ChromaDB (${chunksCount} chunks) + fallback pencarian kata kunci aktif.`
      : `${filesCount} dokumen SOP aktif menggunakan pencarian keyword lokal. Klik Re-index untuk menyinkronkan ke ChromaDB.`;
  }
  if (dlgStatus) {
    dlgStatus.textContent = `${filesCount} dokumen SOP · Indeks ChromaDB: ${chunksCount} chunks · Model: ${ragStatus.model || 'Gemini'}`;
  }
}

function renderSopFilesList() {
  const listEl = document.getElementById('sop-files-list');
  if (!listEl) return;

  if (!sopFiles.length) {
    listEl.innerHTML = '<div style="font-size:12px;color:#64748B;padding:12px;text-align:center;">Belum ada dokumen SOP.</div>';
    return;
  }

  listEl.innerHTML = sopFiles.map(f => `
    <button type="button" class="sop-file-item ${f.filename === currentSopFilename ? 'is-active' : ''}" data-filename="${escapeHtml(f.filename)}">
      <div class="sop-file-name">${escapeHtml(f.filename)}</div>
      <div class="sop-file-meta">${escapeHtml(f.word_count)} kata · ${escapeHtml(f.updated_at)}</div>
    </button>
  `).join('');

  listEl.querySelectorAll('.sop-file-item').forEach(btn => {
    btn.addEventListener('click', () => loadSopFileDetail(btn.dataset.filename));
  });
}

async function loadSopList({ selectFirst = false } = {}) {
  try {
    const res = await fetch(`${API_BASE_URL}/api/ai/knowledge`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Gagal memuat daftar SOP');
    const json = await res.json();
    sopFiles = json.files || [];
    updateRagSummaryCard(json.rag_status);
    renderSopFilesList();

    if (selectFirst && sopFiles.length > 0 && !currentSopFilename) {
      await loadSopFileDetail(sopFiles[0].filename);
    }
  } catch (err) {
    console.warn('[ai] Gagal memuat SOP:', err);
  }
}

async function loadSopFileDetail(filename) {
  if (!filename) return;
  try {
    const res = await fetch(`${API_BASE_URL}/api/ai/knowledge/${encodeURIComponent(filename)}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Gagal membaca dokumen SOP');
    const json = await res.json();
    currentSopFilename = json.file.filename;
    const nameInput = document.getElementById('sop-filename-input');
    const contentInput = document.getElementById('sop-content-input');
    if (nameInput) nameInput.value = json.file.filename;
    if (contentInput) contentInput.value = json.file.content;
    renderSopFilesList();
  } catch (err) {
    toast(err.message, 'warning');
  }
}

async function triggerReindex() {
  toast('Menyinkronkan ulang indeks RAG...', 'info');
  try {
    const res = await fetch(`${API_BASE_URL}/api/ai/knowledge/reindex`, { method: 'POST' });
    const json = await res.json();
    if (!res.ok) throw new Error(json.message || 'Gagal re-index RAG');
    updateRagSummaryCard(json.rag_status);
    if (json.reindex?.warning) {
      toast(json.reindex.warning, 'warning', 5000);
    } else {
      toast(`RAG berhasil di-reindex (${json.reindex?.indexed_chunks || 0} chunks dari ${json.reindex?.indexed_files || 0} SOP).`, 'success');
    }
  } catch (err) {
    toast(`Gagal re-index RAG: ${err.message}`, 'warning');
  }
}

function initSopManager() {
  const dialog = document.getElementById('sop-manager-dialog');
  const openDialog = async () => {
    await loadSopList({ selectFirst: true });
    if (typeof dialog?.showModal === 'function') dialog.showModal();
    else dialog?.setAttribute('open', '');
  };

  document.getElementById('btn-open-sop-manager')?.addEventListener('click', openDialog);
  document.getElementById('btn-open-sop-manager-2')?.addEventListener('click', openDialog);
  document.getElementById('btn-quick-reindex')?.addEventListener('click', triggerReindex);
  document.getElementById('btn-sop-reindex')?.addEventListener('click', triggerReindex);

  document.getElementById('btn-close-sop-dialog')?.addEventListener('click', () => dialog?.close());
  dialog?.addEventListener('click', (e) => {
    if (e.target === dialog) dialog.close();
  });

  document.getElementById('btn-sop-new')?.addEventListener('click', () => {
    currentSopFilename = '';
    const nameInput = document.getElementById('sop-filename-input');
    const contentInput = document.getElementById('sop-content-input');
    if (nameInput) {
      nameInput.value = '';
      nameInput.focus();
    }
    if (contentInput) contentInput.value = '# Judul SOP Baru\n\n';
    renderSopFilesList();
  });

  const uploadBtn = document.getElementById('btn-sop-upload');
  const uploadInput = document.getElementById('sop-file-upload');
  uploadBtn?.addEventListener('click', () => uploadInput?.click());
  uploadInput?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    try {
      const text = await file.text();
      const nameInput = document.getElementById('sop-filename-input');
      const contentInput = document.getElementById('sop-content-input');
      if (nameInput) nameInput.value = file.name;
      if (contentInput) contentInput.value = text;
      toast(`File ${file.name} dimuat ke editor. Klik "Simpan & Re-index" untuk menerapkan.`, 'info');
    } catch {
      toast('Gagal membaca file SOP yang diunggah.', 'warning');
    }
  });

  document.getElementById('sop-editor-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const nameInput = document.getElementById('sop-filename-input');
    const contentInput = document.getElementById('sop-content-input');
    const saveBtn = document.getElementById('btn-sop-save');
    const filename = nameInput?.value.trim() || '';
    const content = contentInput?.value.trim() || '';
    if (!filename || !content) return;

    if (saveBtn) saveBtn.disabled = true;
    try {
      const res = await fetch(`${API_BASE_URL}/api/ai/knowledge`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.message || 'Gagal menyimpan SOP');
      currentSopFilename = json.file.filename;
      if (nameInput) nameInput.value = currentSopFilename;
      await loadSopList();
      if (json.reindex?.warning) {
        toast(`SOP ${currentSopFilename} tersimpan. ${json.reindex.warning}`, 'warning', 5000);
      } else {
        toast(`SOP ${currentSopFilename} tersimpan & RAG diperbarui (${json.reindex?.indexed_chunks || 0} chunks).`, 'success');
      }
    } catch (err) {
      toast(err.message, 'warning');
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  });

  document.getElementById('btn-sop-delete')?.addEventListener('click', async () => {
    const nameInput = document.getElementById('sop-filename-input');
    const filename = currentSopFilename || nameInput?.value.trim() || '';
    if (!filename) {
      toast('Pilih dokumen SOP yang ingin dihapus terlebih dahulu.', 'info');
      return;
    }
    if (!window.confirm(`Hapus dokumen SOP "${filename}" dari basis pengetahuan?`)) return;

    try {
      const res = await fetch(`${API_BASE_URL}/api/ai/knowledge/${encodeURIComponent(filename)}`, {
        method: 'DELETE',
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.message || 'Gagal menghapus SOP');
      currentSopFilename = '';
      if (nameInput) nameInput.value = '';
      const contentInput = document.getElementById('sop-content-input');
      if (contentInput) contentInput.value = '';
      await loadSopList({ selectFirst: true });
      toast(`SOP ${filename} dihapus & RAG diperbarui.`, 'info');
    } catch (err) {
      toast(err.message, 'warning');
    }
  });
}

// ------------------------------------------------------------------
// LAMPIRAN FOTO MULTIMODAL DI CHAT
// ------------------------------------------------------------------
function initPhotoAttachment() {
  const attachBtn = document.getElementById('btn-attach-photo');
  const photoInput = document.getElementById('ai-photo-input');
  attachBtn?.addEventListener('click', () => photoInput?.click());

  photoInput?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      toast('Pilih foto JPG, PNG, atau WebP (maks. 5 MB).', 'warning');
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      pendingPhotoDataUrl = String(reader.result || '');
      pendingPhotoName = file.name;
      updateContextBar();
      userInput?.focus();
      toast(`Foto "${file.name}" siap untuk Audit Visual Multimodal.`, 'info');
    };
    reader.readAsDataURL(file);
  });
}

// ------------------------------------------------------------------
// INIT
// ------------------------------------------------------------------
function init() {
  startClock();

  chatMessages = loadStoredChat();
  renderAllMessages();
  updateContextBar();

  loadProblematicVehicles();
  loadSopList();
  initSopManager();
  initPhotoAttachment();

  document.getElementById('btn-refresh-cases')?.addEventListener('click', () => {
    loadProblematicVehicles();
    toast('Memperbarui daftar kendaraan bermasalah...', 'info');
  });

  document.getElementById('btn-reset-chat')?.addEventListener('click', () => {
    chatMessages = [];
    activeVehicle = null;
    pendingPhotoDataUrl = null;
    pendingPhotoName = '';
    localStorage.removeItem(CHAT_STORAGE_KEY);
    document.querySelectorAll('.ai-case-card').forEach(c => c.classList.remove('is-selected'));
    renderAllMessages();
    updateContextBar();
    toast('Riwayat percakapan & konteks aktif dibersihkan.', 'info');
  });

  chatForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    sendQuery(userInput?.value || '');
  });

  document.querySelectorAll('.ai-prompt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.query;
      if (q) sendQuery(q);
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
