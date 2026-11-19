/**
 * ai_assistant.js — FERQUEUE Web Monitoring
 * Client-side handler for the AI Assistant, dispute resolution & sensor diagnostics workspace.
 */

import { startClock, toast, API_BASE_URL } from './utils.js';

const messagesArea = document.getElementById('ai-chat-messages');
const chatForm     = document.getElementById('ai-chat-form');
const userInput    = document.getElementById('ai-user-input');

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

  let metricsHtml = '';
  if (data.metrics) {
    const items = Object.entries(data.metrics).map(([k, v]) => `
      <div class="ai-metric-item">
        <span class="ai-metric-key">${escapeHtml(k.replace(/_/g, ' '))}</span>
        <span class="ai-metric-val">${escapeHtml(String(v))}</span>
      </div>
    `).join('');
    metricsHtml = `<div class="ai-metrics-grid">${items}</div>`;
  }

  let legalHtml = '';
  if (data.legal_basis) {
    legalHtml = `
      <div class="ai-alert-box">
        <strong>Rujukan Dasar Hukum:</strong> ${escapeHtml(data.legal_basis)}
        ${data.operational_risk ? `<br><strong>Risiko Operasional:</strong> ${escapeHtml(data.operational_risk)}` : ''}
      </div>
    `;
  } else if (data.diagnostic_finding) {
    legalHtml = `
      <div class="ai-alert-box">
        <strong>Temuan Diagnostik:</strong> ${escapeHtml(data.diagnostic_finding)}
      </div>
    `;
  } else if (data.executive_note) {
    legalHtml = `
      <div class="ai-alert-box">
        <strong>Catatan Eksekutif:</strong> ${escapeHtml(data.executive_note)}
      </div>
    `;
  }

  let recHtml = '';
  if (data.recommendation && Array.isArray(data.recommendation)) {
    const listItems = data.recommendation.map(r => `<div>${escapeHtml(r)}</div>`).join('');
    recHtml = `
      <div class="ai-rec-box">
        <div class="ai-rec-title">Rekomendasi Tindakan Petugas Gate:</div>
        <div class="ai-rec-list">${listItems}</div>
      </div>
    `;
  }

  let docHtml = '';
  if (data.document_draft) {
    docHtml = `
      <div class="ai-doc-preview">${escapeHtml(data.document_draft)}</div>
      <div class="ai-doc-action-row">
        <button class="btn btn--outline btn--sm" onclick="window.printDoc()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
            <polyline points="6 9 6 2 18 2 18 9"/>
            <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
            <rect x="6" y="14" width="12" height="8"/>
          </svg>
          <span>Cetak Berita Acara</span>
        </button>
        <button class="btn btn--primary btn--sm" onclick="window.copyDoc()">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="13" height="13">
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
          </svg>
          <span>Salin Teks Resmi</span>
        </button>
      </div>
    `;
    window._lastDocDraft = data.document_draft;
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
      <div class="ai-output-summary">${escapeHtml(data.summary || '')}</div>
      ${metricsHtml}
      ${legalHtml}
      ${recHtml}
      ${docHtml}
    </div>
  `;

  messagesArea.appendChild(msgDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;
}

async function sendQuery(queryText, ticketId = '') {
  if (!queryText.trim()) return;

  appendUserMessage(queryText);
  if (userInput) userInput.value = '';

  // Placeholder thinking indicator
  const loadingDiv = document.createElement('div');
  loadingDiv.className = 'ai-msg ai-msg--assistant';
  loadingDiv.id = 'ai-thinking-indicator';
  loadingDiv.innerHTML = `
    <div class="ai-msg-avatar ai-msg-avatar--assistant">AI</div>
    <div class="ai-msg-bubble" style="color: var(--clr-text-muted); font-style: italic;">
      <span>Sedang menganalisis basis data sensor &amp; regulasi PM 59/2022...</span>
    </div>
  `;
  messagesArea.appendChild(loadingDiv);
  messagesArea.scrollTop = messagesArea.scrollHeight;

  try {
    const res = await fetch(`${API_BASE_URL}/api/ai/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: queryText, ticket_id: ticketId })
    });

    loadingDiv.remove();

    if (res.ok) {
      const result = await res.json();
      appendAssistantMessage(result);
    } else {
      appendAssistantMessage({
        title: 'Kesalahan Sistem AI',
        summary: 'Tidak dapat memproses permintaan reasoning ke server backend.',
      });
    }
  } catch (err) {
    loadingDiv.remove();
    appendAssistantMessage({
      title: 'Koneksi Offline',
      summary: 'Gagal terhubung ke engine AI lokal. Periksa koneksi backend Flask.',
    });
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

window.copyDoc = function() {
  if (window._lastDocDraft) {
    navigator.clipboard.writeText(window._lastDocDraft).then(() => {
      toast('Draft Berita Acara berhasil disalin ke clipboard!', 'success');
    });
  }
};

window.printDoc = function() {
  if (window._lastDocDraft) {
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`<pre style="font-family: monospace; font-size: 14px; padding: 24px;">${window._lastDocDraft}</pre>`);
    printWindow.document.close();
    printWindow.print();
  }
};

function init() {
  startClock();

  if (chatForm) {
    chatForm.addEventListener('submit', (e) => {
      e.preventDefault();
      if (userInput) sendQuery(userInput.value);
    });
  }

  // Clickable Flagged Case Cards
  document.querySelectorAll('.ai-case-card').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.ai-case-card').forEach(c => c.classList.remove('is-selected'));
      card.classList.add('is-selected');
      const q = card.dataset.query;
      const tid = card.querySelector('.ai-case-id')?.textContent || '';
      sendQuery(q, tid);
    });
  });

  // Shortcut prompt buttons
  document.querySelectorAll('.ai-prompt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const q = btn.dataset.query;
      sendQuery(q);
    });
  });
}

document.addEventListener('DOMContentLoaded', init);
