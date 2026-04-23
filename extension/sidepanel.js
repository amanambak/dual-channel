// sidepanel.js — Native Side Panel Logic

let currentCard = null;
let pendingMergeCard = null;
let pendingMergeAt = 0;
const aiCards = new Map();
const container = document.getElementById('transcript-container');
const toggleBtn = document.getElementById('toggle-btn');
const clearBtn = document.getElementById('clear-btn');
const dot = document.getElementById('dot');
const captureModeBtn = document.getElementById('capture-mode-btn');
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
  const speakerLabel = resolveSpeakerLabel(msg.speaker);
  const card = createUtteranceCard(`stored-${Date.now()}-${Math.random()}`, speakerLabel);
  card.stable.textContent = msg.text || '';
  finalizeCard(card);
  container.appendChild(card.element);
}

function renderStoredAiResponse(msg) {
  const card = createAiResponseCard(msg.utteranceId || `stored-${Date.now()}-${Math.random()}`, {
    collapsed: true,
  });
  card.fullText = msg.text || '';
  updateAiCardContent(card, parseAiSections(card.fullText));
  container.appendChild(card.element);
}

async function initializePanel() {
  const messages = await loadStoredMessages();
  renderStoredMessages(messages);

  chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
    if (response) {
      updateCaptureUI(response.active);
      updateCaptureModeUI(response.captureMode);
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

captureModeBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'TOGGLE_CAPTURE_MODE' }, (response) => {
    if (chrome.runtime.lastError || !response) {
      return;
    }
    if (!response.success) {
      alert(response.error || 'Unable to switch mode while capture is running.');
      return;
    }
    updateCaptureModeUI(response.captureMode);
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

function updateCaptureModeUI(mode) {
  const isRtcMode = mode === 'rtc';
  captureModeBtn.textContent = isRtcMode ? 'Mode: RTC' : 'Mode: Google Meet';
}

// ---------------------------------------------------------------------------
// onMessage router
// ---------------------------------------------------------------------------

const SIDEPANEL_MESSAGE_HANDLERS = {
  TRANSCRIPT_UPDATE(message) {
    const { transcript, isFinal, metadata, speaker } = message;
    const speakerLabel = resolveSpeakerLabel(speaker, metadata);
    const now = Date.now();
    const canMergePending =
      pendingMergeCard
      && pendingMergeCard.speakerLabel === speakerLabel
      && now - pendingMergeAt <= 1800;

    if (!currentCard && transcript.trim()) {
      if (canMergePending) {
        currentCard = pendingMergeCard;
        pendingMergeCard = null;
        reviveCard(currentCard);
      } else {
        currentCard = createUtteranceCard(`u-${Date.now()}`, speakerLabel);
        container.appendChild(currentCard.element);
      }
    } else if (currentCard && transcript.trim() && speakerLabel !== currentCard.speakerLabel) {
      finalizeCard(currentCard);
      pendingMergeCard = currentCard;
      pendingMergeAt = Date.now();
      currentCard = createUtteranceCard(`u-${Date.now()}`, speakerLabel);
      container.appendChild(currentCard.element);
    }

    if (currentCard) {
      if (isFinal) {
        appendFinalToCard(currentCard, transcript);
        if (metadata && metadata.speech_final) {
          finalizeCard(currentCard);
          pendingMergeCard = currentCard;
          pendingMergeAt = Date.now();
          currentCard = null;
        }
      } else {
        updateInterimInCard(currentCard, transcript);
      }
      scrollToBottom();
    }
  },

  AI_RESPONSE_CHUNK(message) {
    const { utteranceId, text, isDone, finalText } = message;
    let aiCard = aiCards.get(utteranceId);
    if (!aiCard) {
      collapseOtherAiCards(utteranceId);
      aiCard = createAiResponseCard(utteranceId);
      aiCards.set(utteranceId, aiCard);
      container.appendChild(aiCard.element);
    }
    if (text) appendChunkToAiCard(aiCard, text);
    if (isDone) {
      if (finalText) replaceAiCardWithFinalText(aiCard, finalText);
      finalizeAiCard(aiCard);
    }
    scrollToBottom();
  },

  CAPTURE_STATUS_CHANGED(message) { updateCaptureUI(message.active); },
  CAPTURE_MODE_CHANGED(message)   { updateCaptureModeUI(message.captureMode); },

  UTTERANCE_END() {
    if (currentCard) {
      finalizeCard(currentCard);
      pendingMergeCard = currentCard;
      pendingMergeAt = Date.now();
      currentCard = null;
    }
  },

  API_ERROR(message) { addErrorToContainer(message.message, message.source); },
};

chrome.runtime.onMessage.addListener((message) => {
  const handler = SIDEPANEL_MESSAGE_HANDLERS[message.type];
  if (handler) handler(message);
});

function scrollToBottom() {
  container.scrollTop = container.scrollHeight;
}

function createUtteranceCard(id, speakerLabel = 'Customer') {
  const el = document.createElement('div');
  el.className = 'utterance-card';
  const badge = document.createElement('div');
  badge.className = `speaker-tag ${speakerLabel === 'Agent' ? 'agent' : 'customer'}`;
  badge.textContent = speakerLabel;
  const textWrap = document.createElement('div');
  textWrap.className = 'utterance-text';
  const stable = document.createElement('span');
  const interim = document.createElement('span');
  interim.style.color = '#888';
  textWrap.appendChild(stable);
  textWrap.appendChild(interim);
  el.appendChild(badge);
  el.appendChild(textWrap);
  return { element: el, stable, interim, id, badge, speakerLabel };
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

function reviveCard(card) {
  card.element.classList.remove('finalized');
}

function resolveSpeakerLabel(speaker, metadata) {
  if (speaker === '1') {
    return 'Agent';
  }
  if (speaker === '0') {
    return 'Customer';
  }
  const channel = metadata?.channel;
  if (channel === 'agent') {
    return 'Agent';
  }
  return 'Customer';
}

function createAiResponseCard(id, options = {}) {
  const collapsed = options.collapsed ?? false;
  const el = document.createElement('div');
  el.className = 'ai-response-card';
  el.dataset.utteranceId = id;

  const header = document.createElement('div');
  header.className = 'ai-response-header';

  const title = document.createElement('div');
  title.className = 'ai-response-title';
  title.textContent = 'AI Response';

  const controls = document.createElement('div');
  controls.className = 'ai-response-controls';

  const collapseBtn = document.createElement('button');
  collapseBtn.type = 'button';
  collapseBtn.className = 'ai-collapse-button';
  collapseBtn.textContent = 'Collapse';

  const body = document.createElement('div');
  body.className = 'ai-response-body';

  const customerInfoLabel = document.createElement('div');
  customerInfoLabel.className = 'ai-section-label loading';
  customerInfoLabel.textContent = 'Customer Info';

  const customerInfo = document.createElement('div');
  customerInfo.className = 'ai-context';

  const suggestionLabel = document.createElement('div');
  suggestionLabel.className = 'ai-section-label loading';
  suggestionLabel.textContent = 'Suggestion';

  const content = document.createElement('div');
  content.className = 'ai-suggestion';

  const copyBtn = document.createElement('button');
  copyBtn.className = 'copy-button';
  copyBtn.textContent = 'Copy';

  controls.appendChild(collapseBtn);
  controls.appendChild(copyBtn);
  header.appendChild(title);
  header.appendChild(controls);

  body.appendChild(customerInfoLabel);
  body.appendChild(customerInfo);
  body.appendChild(suggestionLabel);
  body.appendChild(content);

  el.appendChild(header);
  el.appendChild(body);

  const card = {
    element: el,
    customerInfoLabel,
    customerInfo,
    suggestionLabel,
    content,
    copyBtn,
    collapseBtn,
    body,
    id,
    fullText: '',
    collapsed: false,
  };

  collapseBtn.onclick = () => toggleAiCardCollapse(card);
  copyBtn.onclick = () => {
    navigator.clipboard.writeText(card.content.textContent || '');
    copyBtn.textContent = 'Copied!';
    setTimeout(() => {
      copyBtn.textContent = 'Copy';
    }, 2000);
  };

  setAiCardCollapsed(card, collapsed);
  return card;
}

function appendChunkToAiCard(card, text) {
  card.fullText += text;
  const parsed = parseAiSections(card.fullText);
  updateAiCardContent(card, parsed);
}

function replaceAiCardWithFinalText(card, finalText) {
  card.fullText = finalText;
  appendChunkToAiCard(card, '');
}

function parseAiSections(text) {
  const normalized = (text || '').replace(/\s+/g, ' ').trim();
  const summaryMatch = normalized.match(/\[SUMMARY\](.*?)(?=\[INFO\]|\[CUSTOMER_INFO\]|\[SUGGESTION\]|\[ANSWER\]|$)/i);
  // Support both [INFO] and [CUSTOMER_INFO]
  const customerInfoMatch = normalized.match(/\[INFO\](.*?)(?=\[CUSTOMER_INFO\]|\[SUGGESTION\]|\[ANSWER\]|$)/i)
    || normalized.match(/\[CUSTOMER_INFO\](.*?)(?=\[SUGGESTION\]|\[ANSWER\]|$)/i);
  const suggestionMatch = normalized.match(/\[(?:SUGGESTION|ANSWER)\](.*?)(?=\[INFO\]|\[CUSTOMER_INFO\]|$)/i);

  let summary = summaryMatch ? summaryMatch[1].trim() : '';
  let customerInfo = customerInfoMatch ? customerInfoMatch[1].trim() : '';
  let suggestion = suggestionMatch ? suggestionMatch[1].trim() : normalized;

  summary = summary.replace(/^context:\s*/i, '').replace(/^topic:\s*/i, '').trim();
  customerInfo = customerInfo.replace(/^(customer\s*info:\s*|info:\s*)/i, '').trim();
  suggestion = suggestion.replace(/^suggestion:\s*/i, '').replace(/^answer:\s*/i, '').replace(/^topic:\s*/i, '').trim();
  suggestion = suggestion.replace(/\{[^{}]*\}\s*$/, '').trim();

  if (summary && suggestion.startsWith(summary)) {
    suggestion = suggestion.slice(summary.length).trim();
  }

  if (!suggestion) {
    suggestion = 'Suggestion is being prepared.';
  }

  return { summary, customerInfo, suggestion };
}

function finalizeAiCard(card) {
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

function updateAiCardContent(card, parsed) {
  card.customerInfoLabel.classList.remove('loading');
  card.suggestionLabel.classList.remove('loading');
  card.customerInfoLabel.style.display = parsed.customerInfo ? 'block' : 'none';
  card.customerInfo.textContent = parsed.customerInfo;
  card.customerInfo.style.display = parsed.customerInfo ? 'block' : 'none';
  card.content.textContent = parsed.suggestion;
}

function setAiCardCollapsed(card, collapsed) {
  card.collapsed = collapsed;
  card.element.classList.toggle('collapsed', collapsed);
  card.collapseBtn.textContent = collapsed ? 'Expand' : 'Collapse';
}

function toggleAiCardCollapse(card) {
  setAiCardCollapsed(card, !card.collapsed);
}

function collapseOtherAiCards(activeId) {
  for (const [utteranceId, card] of aiCards.entries()) {
    if (utteranceId !== activeId) {
      setAiCardCollapsed(card, true);
    }
  }
}

function addErrorToContainer(msg, source) {
  const el = document.createElement('div');
  el.className = 'error-card';
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
