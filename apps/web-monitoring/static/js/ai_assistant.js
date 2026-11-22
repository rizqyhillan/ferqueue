/**
 * ai_assistant.js — FERQUEUE Web Monitoring
 * Client-side handler for the AI Assistant, RAG reasoning & overweight vehicle advisor.
 */

import { startClock, toast, API_BASE_URL } from './utils.js';

const messagesArea = document.getElementById('ai-chat-messages');
const chatForm     = document.getElementById('ai-chat-form');
const userInput    = document.getElementById('ai-user-input');
const casesContainer = document.getElementById('ai-cases-container');

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function formatMarkdown(text) {
  if (!text) return '';
  let formatted = escapeHtml(text);

  // Headers: ### Header
  formatted = formatted.replace(/^### (.*$)/gim, '<h4 style="margin: 8px 0 4px; font-size: 13px; font-weight: 700; color: #0F172A;">$1</h4>');
  formatted = formatted.replace(/^## (.*$)/gim, '<h3 style="margin: 10px 0 6px; font-size: 14px; font-weight: 700; color: #0F172A;">$1</h3>');

  // Bold: **text**
  formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

  // Italics: *text*
  formatted = formatted.replace(/\*(.*?)\*/g, '<em>$1</em>');

  // Lists: - item
  formatted = formatted.replace(/^\s*-\s+(.*$)/gim, '<li style="margin-left: 16px; margin-bottom: 2px;">$1</li>');

  // Newlines
  formatted = formatted.replace(/\n/g, '<br>');

  return formatted;
}

function appendUserMessage(text) {
  const msgDiv = document.createElement('div');
  msgDiv.className = 'ai-msg ai-msg--user';
  msgDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--user">OP</div>
    <div class="ai-msg-bubble">${escapeHtml(text)}</div>
  `;
  messagesArea.appendChild(msgDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;
}

function appendAssistantMessage(data) {
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
            <span class="ai-vehicle-val" style="${v.kelebihan_berat_gram > 0 ? 'color:#DC2626;' : ''}">+${escapeHtml(v.kelebihan_berat_gram)} g (${escapeHtml(v.persentase_kelebihan || '0%')})</span>
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

  msgDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--assistant">AI</div>
    <div class="ai-msg-bubble">
      <div class="ai-output-title">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="15" height="15" style="color:#7E22CE;">
          <path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>
        </svg>
        <span>${escapeHtml(data.title || 'Analisis Cerdas FERQUEUE')}</span>
      </div>
      ${vehicleHtml}
      <div class="ai-output-summary" style="line-height: 1.6;">${formatMarkdown(data.summary || '')}</div>
    </div>
  `;

  messagesArea.appendChild(msgDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;
}

async function sendQuery(queryText, idPemeriksaan = '') {
  if (!queryText.trim()) return;

  appendUserMessage(queryText);
  if (userInput) userInput.value = '';

  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'ai-msg ai-msg--assistant';
  loadingDiv.id = 'ai-thinking-indicator';
  loadingDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--assistant">AI</div>
    <div class="ai-msg-bubble" style="color: var(--clr-text-muted); font-style: italic;">
      <span>Sedang menganalisis basis SOP FERQUEUE &amp; Permenhub PM 103/2017 via Gemini RAG...</span>
    </div>
  `;
  messagesArea.appendChild(loadingDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;

  try {
    const payload = { query: queryText };
    if (idPemeriksaan) payload.id_pemeriksaan = idPemeriksaan;

    const res = await fetch(`${API_BASE_URL}/api/ai/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    loadingDiv.remove();

    if (res.ok) {
      const result = await res.json();
      appendAssistantMessage(result);
    } else {
      const errJson = await res.json().catch(() => ({}));
      appendAssistantMessage({
        title: 'Pemberitahuan Sistem AI',
        summary: errJson.message || 'Tidak dapat memproses permintaan reasoning ke server backend.',
      });
    }
  } catch (err) {
    loadingDiv.remove();
    appendAssistantMessage({
      title: 'Koneksi Offline',
      summary: 'Gagal terhubung ke engine AI backend. Pastikan server Flask aktif di port 5000.',
    });
  }
}

async function loadProblematicVehicles() {
  if (!casesContainer) return;
  casesContainer.innerHTML = `
    <div style="font-size: 12px; color: var(--clr-text-muted); text-align: center; padding: 12px 0;">
      Memperbarui data dari MySQL...
    </div>
  `;

  try {
    const res = await fetch(`${API_BASE_URL}/api/kendaraan-bermasalah`);
    if (!res.ok) throw new Error('Gagal mengambil data kendaraan');
    const json = await res.json();
    const list = json.data || [];

    if (list.length === 0) {
      casesContainer.innerHTML = `
        <div style="font-size: 12px; color: var(--clr-text-muted); text-align: center; padding: 16px 8px; line-height: 1.5;">
          Belum ada kendaraan berstatus <strong>Overweight</strong> di database.<br>
          <span style="font-size: 11px;">Gunakan tombol pertanyaan cepat di bawah atau ketik pertanyaan langsung di kolom chat.</span>
        </div>
      `;
      return;
    }

    casesContainer.innerHTML = '';
    list.slice(0, 10).forEach(item => {
      const card = document.createElement('div');
      card.className = 'ai-case-card';
      card.dataset.id = item.id_pemeriksaan;

      const kelebihan = item.kelebihan_berat_gram || 0;
      const pct = item.persentase_kelebihan || '0%';
      const isHeavy = String(item.kategori_overweight || '').includes('Berat');

      card.innerHTML = `
        <div class="ai-case-top">
          <span class="ai-case-id">${escapeHtml(item.id_pemeriksaan)}</span>
          <span class="ai-case-badge ${isHeavy ? 'ai-case-badge--danger' : 'ai-case-badge--warning'}">
            +${kelebihan}g (${pct})
          </span>
        </div>
        <div class="ai-case-driver">${escapeHtml(item.nama_pengemudi || 'Pengemudi')} · ${escapeHtml(item.jenis_kendaraan)} (Gol. ${escapeHtml(item.golongan)})</div>
        <div class="ai-case-meta">Berat: ${item.berat_aktual_gram}g · Batas: ${item.batas_maksimum_gram}g · ${escapeHtml(item.kategori_overweight || '-')}</div>
      `;

      card.addEventListener('click', () => {
        document.querySelectorAll('.ai-case-card').forEach(c => c.classList.remove('is-selected'));
        card.classList.add('is-selected');
        sendQuery(`Analisis pelanggaran kendaraan ${item.id_pemeriksaan} dan berikan langkah penanganannya di lapangan`, item.id_pemeriksaan);
      });

      casesContainer.appendChild(card);
    });
  } catch (err) {
    casesContainer.innerHTML = `
      <div style="font-size: 11.5px; color: #EF4444; text-align: center; padding: 12px 0;">
        Gagal memuat dari MySQL (${escapeHtml(err.message)}).
      </div>
    `;
  }
}

function init() {
  startClock();
  loadProblematicVehicles();

  document.getElementById('btn-refresh-cases')?.addEventListener('click', () => {
    loadProblematicVehicles();
    toast('Memperbarui daftar kendaraan bermasalah...', 'info');
  });

  if (chatForm) {
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (userInput && userInput.value.trim()) {
        sendQuery(userInput.value.trim());
      }
    });
  }

  // Shortcut prompt buttons
  document.querySelectorAll('.ai-prompt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.query;
      sendQuery(q);
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
