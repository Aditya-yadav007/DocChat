// ═══════════════════════════════════════════════════════════
//  DocChat AI — Frontend Logic (with background index polling)
// ═══════════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
  // ── Element refs ─────────────────────────────────────────
  const $ = (s) => document.getElementById(s);
  const uploadZone   = $('uploadZone');
  const fileInput    = $('fileInput');
  const uploadProg   = $('uploadProgress');
  const progressFill = $('progressFill');
  const progressText = $('progressText');
  const docList      = $('docList');
  const messages     = $('messages');
  const welcome      = $('welcomeScreen');
  const queryInput   = $('queryInput');
  const sendBtn      = $('sendBtn');
  const newChatBtn   = $('newChatBtn');
  const themeToggle  = $('themeToggle');
  const statusText   = $('statusText');
  const statusDot    = document.querySelector('.status-dot');
  const sidebar      = $('sidebar');
  const mobileToggle = $('mobileToggle');

  // ── Theme ────────────────────────────────────────────────
  const savedTheme = localStorage.getItem('theme') || 'dark';
  setTheme(savedTheme);

  themeToggle.addEventListener('click', () => {
    const next = document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    setTheme(next);
  });

  function setTheme(t) {
    document.documentElement.setAttribute('data-theme', t);
    localStorage.setItem('theme', t);
    themeToggle.textContent = t === 'dark' ? '🌙' : '☀️';
  }

  // ── Mobile sidebar ──────────────────────────────────────
  mobileToggle.addEventListener('click', () => sidebar.classList.toggle('open'));

  // ── Load initial data ───────────────────────────────────
  loadDocuments();
  loadHistory();

  // ── File Upload (click + drag-drop) ─────────────────────
  uploadZone.addEventListener('click', () => fileInput.click());

  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('drag-over');
  });
  uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('drag-over');
    if (e.dataTransfer.files.length) uploadFiles(e.dataTransfer.files);
  });
  fileInput.addEventListener('change', () => {
    if (fileInput.files.length) uploadFiles(fileInput.files);
    fileInput.value = '';
  });

  async function uploadFiles(files) {
    const fd = new FormData();
    for (const f of files) fd.append('files', f);

    showProgress('Uploading...', 20);
    setStatus('Uploading...', true);

    try {
      const resp = await fetch('/upload', { method: 'POST', body: fd });
      const data = await resp.json();

      if (resp.ok && data.status === 'ok') {
        showProgress('Indexing in background...', 50);
        loadDocuments();
        // Poll for index completion
        pollIndexStatus();
      } else {
        showProgress(data.message || 'Upload failed', 0);
        setStatus('Error', false);
        hideProgressAfter(3000);
      }
    } catch (e) {
      showProgress('Network error', 0);
      setStatus('Error', false);
      hideProgressAfter(3000);
    }
  }

  // ── Index status polling ─────────────────────────────────
  let pollTimer = null;

  function pollIndexStatus() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(async () => {
      try {
        const resp = await fetch('/index-status');
        const data = await resp.json();
        if (data.busy) {
          showProgress(data.message, 70);
          setStatus(data.message, true);
        } else {
          showProgress('Done!', 100);
          setStatus('Ready', false);
          clearInterval(pollTimer);
          pollTimer = null;
          loadDocuments();
          hideProgressAfter(1500);
        }
      } catch (e) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }, 1000);
  }

  // ── Progress bar helpers ─────────────────────────────────
  function showProgress(msg, pct) {
    uploadProg.style.display = 'block';
    progressFill.style.width = pct + '%';
    progressText.textContent = msg;
  }
  function hideProgressAfter(ms) {
    setTimeout(() => { uploadProg.style.display = 'none'; }, ms);
  }

  // ── Status badge ─────────────────────────────────────────
  function setStatus(txt, busy) {
    statusText.textContent = txt;
    if (statusDot) {
      statusDot.style.background = busy ? '#f59e0b' : '#22c55e';
    }
  }

  // ── Documents list ──────────────────────────────────────
  async function loadDocuments() {
    try {
      const resp = await fetch('/documents');
      const data = await resp.json();
      renderDocuments(data.documents || []);
    } catch (e) {
      docList.innerHTML = '<p style="font-size:0.75rem;color:var(--text-muted);">Could not load documents.</p>';
    }
  }

  function renderDocuments(docs) {
    if (!docs.length) {
      docList.innerHTML = '<p style="font-size:0.75rem;color:var(--text-muted);padding:0.5rem;">No documents yet.</p>';
      return;
    }
    docList.innerHTML = docs.map(d => `
      <div class="doc-item">
        <span class="doc-badge">${d.type}</span>
        <span class="doc-name" title="${d.name}">${d.name}</span>
        <span class="doc-size">${formatSize(d.size)}</span>
        <button class="doc-delete" data-path="${d.path}" title="Delete">✕</button>
      </div>
    `).join('');

    docList.querySelectorAll('.doc-delete').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const path = btn.dataset.path;
        if (!confirm('Delete this document? The index will be rebuilt.')) return;
        setStatus('Deleting...', true);
        try {
          const resp = await fetch('/delete-document', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path })
          });
          if (resp.ok) {
            loadDocuments();
            pollIndexStatus(); // poll until rebuild finishes
          }
        } catch (e) { setStatus('Error', false); }
      });
    });
  }

  // ── Chat ────────────────────────────────────────────────
  sendBtn.addEventListener('click', sendQuery);
  queryInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendQuery(); }
  });

  async function sendQuery() {
    const query = queryInput.value.trim();
    if (!query) return;

    // Hide welcome
    if (welcome) welcome.style.display = 'none';

    appendMessage('user', query);
    queryInput.value = '';
    sendBtn.disabled = true;
    setStatus('Thinking...', true);

    const typing = showTyping();

    try {
      const resp = await fetch('/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query })
      });
      const data = await resp.json();
      removeTyping(typing);

      if (resp.ok && data.status === 'ok') {
        appendMessage('assistant', data.answer, data.sources || []);
      } else {
        appendMessage('assistant', data.message || 'Error retrieving answer.');
      }
    } catch (e) {
      removeTyping(typing);
      appendMessage('assistant', 'Network error. Please try again.');
    }

    sendBtn.disabled = false;
    setStatus('Ready', false);
    queryInput.focus();
  }

  function appendMessage(role, content, sources = []) {
    const div = document.createElement('div');
    div.className = `msg ${role}`;

    const avatar = role === 'user' ? '👤' : '🤖';
    let sourcesHTML = '';
    if (sources.length) {
      sourcesHTML = `<div class="msg-sources">${sources.map(s => `<span class="source-tag">📄 ${s}</span>`).join('')}</div>`;
    }

    div.innerHTML = `
      <div class="msg-avatar">${avatar}</div>
      <div class="msg-body">
        <div class="msg-content">${escapeHTML(content)}</div>
        ${sourcesHTML}
      </div>`;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    const div = document.createElement('div');
    div.className = 'typing-indicator';
    div.innerHTML = `
      <div class="msg-avatar" style="background:var(--bg-card);border:1px solid var(--border);">🤖</div>
      <div class="typing-dots"><span></span><span></span><span></span></div>`;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
    return div;
  }
  function removeTyping(el) { if (el && el.parentNode) el.parentNode.removeChild(el); }

  // ── Chat history ────────────────────────────────────────
  async function loadHistory() {
    try {
      const resp = await fetch('/history');
      const data = await resp.json();
      if (data.history && data.history.length) {
        welcome.style.display = 'none';
        data.history.forEach(m => appendMessage(m.role, m.content, m.sources || []));
      }
    } catch (e) { /* ignore */ }
  }

  newChatBtn.addEventListener('click', async () => {
    try { await fetch('/clear-history', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' }); } catch (e) { /* ok */ }
    messages.innerHTML = '';
    if (welcome) {
      messages.appendChild(welcome);
      welcome.style.display = 'flex';
    }
  });

  // ── Helpers ─────────────────────────────────────────────
  function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function escapeHTML(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
});
