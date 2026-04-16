// sidepanel.js — Native Side Panel Logic

let currentCard = null;
const aiCards = new Map();
const container = document.getElementById('transcript-container');
const toggleBtn = document.getElementById('toggle-btn');
const clearBtn = document.getElementById('clear-btn');
const dot = document.getElementById('dot');
const summaryBtn = document.getElementById('summary-btn');
const summaryModal = document.getElementById('summary-modal');
const modalClose = document.getElementById('modal-close');
const modalBody = document.getElementById('modal-body');

async function loadStoredMessages() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'LOAD_MESSAGES' }, (response) => {
      resolve(response?.messages || []);
    });
  });
}

function renderStoredMessages(messages) {
  for (const msg of messages) {
    if (msg.type === 'user') {
      renderStoredUtterance(msg);
    } else if (msg.type === 'ai') {
      renderStoredAiResponse(msg);
    }
  }
  scrollToBottom();
}

function renderStoredUtterance(msg) {
  const card = document.createElement('div');
  card.className = 'utterance-card finalized';
  card.textContent = msg.text;
  container.appendChild(card);
}

function renderStoredAiResponse(msg) {
  const parsed = parseAiSections(msg.text);
  const card = document.createElement('div');
  card.className = 'ai-response-card';

  const contextLabel = document.createElement('div');
  contextLabel.className = 'ai-section-label';
  contextLabel.textContent = 'Context';

  const summary = document.createElement('div');
  summary.className = 'ai-context';
  summary.textContent = parsed.summary;

  const customerInfoLabel = document.createElement('div');
  customerInfoLabel.className = 'ai-section-label';
  customerInfoLabel.textContent = 'Customer Info';

  const customerInfo = document.createElement('div');
  customerInfo.className = 'ai-context';
  customerInfo.textContent = parsed.customerInfo;
  customerInfo.style.display = parsed.customerInfo ? 'block' : 'none';
  customerInfoLabel.style.display = parsed.customerInfo ? 'block' : 'none';

  const suggestionLabel = document.createElement('div');
  suggestionLabel.className = 'ai-section-label';
  suggestionLabel.textContent = 'Suggestion';

  const content = document.createElement('div');
  content.className = 'ai-suggestion';
  content.textContent = parsed.suggestion;

  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-button';
  copyBtn.textContent = 'Copy';
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(parsed.suggestion);
    copyBtn.textContent = 'Copied!';
    setTimeout(() => {
      copyBtn.textContent = 'Copy';
    }, 2000);
  };

  card.appendChild(contextLabel);
  card.appendChild(summary);
  card.appendChild(customerInfoLabel);
  card.appendChild(customerInfo);
  card.appendChild(suggestionLabel);
  card.appendChild(content);
  card.appendChild(copyBtn);
  container.appendChild(card);
}

async function initializePanel() {
  const messages = await loadStoredMessages();
  renderStoredMessages(messages);

  chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
    if (response) {
      updateCaptureUI(response.active);
    }
  });
}

initializePanel();

toggleBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'TOGGLE_CAPTURE' }, (response) => {
    if (chrome.runtime.lastError) {
      return;
    }
    if (response) {
      updateCaptureUI(response.active);
    }
  });
});

clearBtn.addEventListener('click', () => {
  container.innerHTML = '';
  currentCard = null;
  aiCards.clear();
  chrome.runtime.sendMessage({ type: 'CLEAR_MESSAGES' }, () => {});
});

summaryBtn.addEventListener('click', async () => {
  const messages = await loadStoredMessages();
  if (messages.length === 0) {
    alert('No conversation data available. Start a conversation first.');
    return;
  }

  const btnText = document.getElementById('summary-btn-text');
  const originalText = btnText.textContent;
  btnText.innerHTML = '<span class="loading-spinner"></span> Generating...';
  summaryBtn.disabled = true;

  try {
    const summary = await new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'GENERATE_SUMMARY' }, (response) => {
        resolve(response?.summary);
      });
    });
    displaySummary(summary);
  } catch (err) {
    alert('Failed to generate summary. Please try again.');
  } finally {
    btnText.textContent = originalText;
    summaryBtn.disabled = false;
  }
});

modalClose.addEventListener('click', () => {
  summaryModal.classList.remove('active');
});

summaryModal.addEventListener('click', (e) => {
  if (e.target === summaryModal) {
    summaryModal.classList.remove('active');
  }
});

document.getElementById('mic-permission-btn').addEventListener('click', () => {
  chrome.tabs.create({ url: chrome.runtime.getURL('permission.html') });
});

function updateCaptureUI(isActive) {
  if (isActive) {
    toggleBtn.textContent = 'Stop Capture';
    toggleBtn.classList.add('active');
    dot.classList.add('active');
  } else {
    toggleBtn.textContent = 'Start Capture';
    toggleBtn.classList.remove('active');
    dot.classList.remove('active');
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.type === 'TRANSCRIPT_UPDATE') {
    const { transcript, isFinal, metadata } = message;

    if (!currentCard && transcript.trim()) {
      const utteranceId = `u-${Date.now()}`;
      currentCard = createUtteranceCard(utteranceId);
      container.appendChild(currentCard.element);
    }

    if (currentCard) {
      if (isFinal) {
        appendFinalToCard(currentCard, transcript);
        if (metadata && metadata.speech_final) {
          finalizeCard(currentCard);
          currentCard = null;
        }
      } else {
        updateInterimInCard(currentCard, transcript);
      }
      scrollToBottom();
    }
  }

  if (message.type === 'AI_RESPONSE_CHUNK') {
    const { utteranceId, text, isDone, finalText } = message;
    let aiCard = aiCards.get(utteranceId);

    if (!aiCard) {
      aiCard = createAiResponseCard(utteranceId);
      aiCards.set(utteranceId, aiCard);
      container.appendChild(aiCard.element);
    }

    if (text) {
      appendChunkToAiCard(aiCard, text);
    }

    if (isDone) {
      if (finalText) {
        replaceAiCardWithFinalText(aiCard, finalText);
      }
      finalizeAiCard(aiCard);
    }
    scrollToBottom();
  }

  if (message.type === 'CAPTURE_STATUS_CHANGED') {
    updateCaptureUI(message.active);
  }

  if (message.type === 'UTTERANCE_END') {
    if (currentCard) {
      finalizeCard(currentCard);
      currentCard = null;
    }
  }

  if (message.type === 'API_ERROR') {
    addErrorToContainer(message.message, message.source);
  }
});

function scrollToBottom() {
  container.scrollTop = container.scrollHeight;
}

function createUtteranceCard(id) {
  const el = document.createElement('div');
  el.className = 'utterance-card';
  const stable = document.createElement('span');
  const interim = document.createElement('span');
  interim.style.color = '#888';
  el.appendChild(stable);
  el.appendChild(interim);
  return { element: el, stable, interim, id };
}

function updateInterimInCard(card, text) {
  card.interim.textContent = text ? ` ${text}` : '';
}

function appendFinalToCard(card, text) {
  if (!text) {
    return;
  }
  const current = card.stable.textContent;
  if (current && !current.endsWith(' ') && !text.startsWith(' ')) {
    card.stable.textContent += ' ';
  }
  card.stable.textContent += text;
  card.interim.textContent = '';
}

function finalizeCard(card) {
  card.element.classList.add('finalized');
  card.interim.textContent = '';
}

function createAiResponseCard(id) {
  const el = document.createElement('div');
  el.className = 'ai-response-card';

  const contextLabel = document.createElement('div');
  contextLabel.className = 'ai-section-label loading';
  contextLabel.textContent = 'Context';

  const summary = document.createElement('div');
  summary.className = 'ai-context';

  const customerInfoLabel = document.createElement('div');
  customerInfoLabel.className = 'ai-section-label loading';
  customerInfoLabel.textContent = 'Customer Info';
  customerInfoLabel.style.display = 'none';

  const customerInfo = document.createElement('div');
  customerInfo.className = 'ai-context';
  customerInfo.style.display = 'none';

  const suggestionLabel = document.createElement('div');
  suggestionLabel.className = 'ai-section-label loading';
  suggestionLabel.textContent = 'Suggestion';

  const content = document.createElement('div');
  content.className = 'ai-suggestion';

  el.appendChild(contextLabel);
  el.appendChild(summary);
  el.appendChild(customerInfoLabel);
  el.appendChild(customerInfo);
  el.appendChild(suggestionLabel);
  el.appendChild(content);

  return { element: el, contextLabel, summary, customerInfoLabel, customerInfo, suggestionLabel, content, id, fullText: '' };
}

function appendChunkToAiCard(card, text) {
  card.fullText += text;
  const parsed = parseAiSections(card.fullText);
  card.summary.textContent = parsed.summary;
  card.customerInfo.textContent = parsed.customerInfo;
  card.customerInfo.style.display = parsed.customerInfo ? 'block' : 'none';
  card.customerInfoLabel.style.display = parsed.customerInfo ? 'block' : 'none';
  card.content.textContent = parsed.suggestion;
}

function replaceAiCardWithFinalText(card, finalText) {
  card.fullText = finalText;
  card.summary.textContent = '';
  card.customerInfo.textContent = '';
  card.customerInfo.style.display = 'none';
  card.customerInfoLabel.style.display = 'none';
  card.content.textContent = '';
  card.contextLabel.classList.add('loading');
  card.customerInfoLabel.classList.add('loading');
  card.suggestionLabel.classList.add('loading');
  appendChunkToAiCard(card, '');
}

function parseAiSections(text) {
  const normalized = (text || '').replace(/\s+/g, ' ').trim();
  const summaryMatch = normalized.match(/\[SUMMARY\](.*?)(?=\[CUSTOMER_INFO\]|\[SUGGESTION\]|\[ANSWER\]|$)/i);
  const customerInfoMatch = normalized.match(/\[CUSTOMER_INFO\](.*?)(?=\[SUGGESTION\]|\[ANSWER\]|$)/i);
  const suggestionMatch = normalized.match(/\[(?:SUGGESTION|ANSWER)\](.*)$/i);

  let summary = summaryMatch ? summaryMatch[1].trim() : '';
  let customerInfo = customerInfoMatch ? customerInfoMatch[1].trim() : '';
  let suggestion = suggestionMatch ? suggestionMatch[1].trim() : normalized;

  summary = summary.replace(/^context:\s*/i, '').replace(/^topic:\s*/i, '').trim();
  customerInfo = customerInfo.replace(/^customer info:\s*/i, '').trim();
  suggestion = suggestion.replace(/^suggestion:\s*/i, '').replace(/^answer:\s*/i, '').replace(/^topic:\s*/i, '').trim();

  if (summary && suggestion.startsWith(summary)) {
    suggestion = suggestion.slice(summary.length).trim();
  }

  if (!summary) {
    summary = 'Current customer discussion';
  }
  if (!suggestion) {
    suggestion = 'Suggestion is being prepared.';
  }

  return { summary, customerInfo, suggestion };
}

function finalizeAiCard(card) {
  if (!card.copyBtn) {
    const btn = document.createElement('button');
    btn.className = 'copy-button';
    btn.textContent = 'Copy';
    btn.onclick = () => {
      navigator.clipboard.writeText(card.content.textContent);
      btn.textContent = 'Copied!';
      setTimeout(() => {
        btn.textContent = 'Copy';
      }, 2000);
    };
    card.element.appendChild(btn);
    card.copyBtn = btn;
  }

  if (!card.speakBtn && card.content.textContent.includes('Ask:')) {
    const speakBtn = document.createElement('button');
    speakBtn.className = 'copy-button';
    speakBtn.textContent = 'Speak';
    speakBtn.onclick = () => {
      const utterance = new SpeechSynthesisUtterance(card.content.textContent.replace('[SUGGESTION] Ask:', '').trim());
      speechSynthesis.speak(utterance);
    };
    card.element.appendChild(speakBtn);
    card.speakBtn = speakBtn;
  }
}

function addErrorToContainer(msg, source) {
  const el = document.createElement('div');
  el.style.cssText = 'background:#3a1e1e; border:1px solid #ff6b6b; padding:12px; border-radius:8px; color:#ff6b6b; font-size:0.9rem;';
  el.textContent = `[${source}] Error: ${msg}`;
  container.appendChild(el);
  scrollToBottom();
}

function displaySummary(summary) {
  const customerInfo = summary?.customer_info || {};
  const entries = Object.entries(customerInfo);

  if (entries.length === 0) {
    modalBody.innerHTML = `
      <div class="summary-section">
        <h3>Customer Info</h3>
        <div class="summary-card">
          <div class="summary-row">
            <div class="summary-key">status</div>
            <div class="summary-value">No customer info found.</div>
          </div>
        </div>
      </div>
    `;
    summaryModal.classList.add('active');
    return;
  }

  const html = entries.map(([key, value]) => `
    <div class="summary-row">
      <div class="summary-key">${escapeHtml(key)}</div>
      <div class="summary-value">${escapeHtml(value)}</div>
    </div>
  `).join('');

  modalBody.innerHTML = `
    <div class="summary-section">
      <h3>Customer Info</h3>
      <div class="summary-card">${html}</div>
    </div>
  `;
  summaryModal.classList.add('active');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
