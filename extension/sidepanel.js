// sidepanel.js — Native Side Panel Logic

import { normalizeLeadIdInput } from './utils.js';

let currentCard = null;
let pendingMergeCard = null;
let pendingMergeAt = 0;
const aiCards = new Map();
const container = document.getElementById('transcript-container');
const callTabBtn = document.getElementById('call-tab');
const chatTabBtn = document.getElementById('chat-tab');
const callView = document.getElementById('call-view');
const chatView = document.getElementById('chat-view');
const toggleBtn = document.getElementById('toggle-btn');
const pauseAgentBtn = document.getElementById('pause-agent-btn');
const clearBtn = document.getElementById('clear-btn');
const dot = document.getElementById('dot');
const captureModeBtn = document.getElementById('capture-mode-btn');
const summaryBtn = document.getElementById('summary-btn');
const summaryModal = document.getElementById('summary-modal');
const modalClose = document.getElementById('modal-close');
const modalBody = document.getElementById('modal-body');
const chatLog = document.getElementById('chat-log');
const chatForm = document.getElementById('chat-form');
const chatInput = document.getElementById('chat-input');
const chatSendBtn = document.getElementById('chat-send-btn');
const clearChatBtn = document.getElementById('clear-chat-btn');
const leadIdForm = document.getElementById('lead-id-form');
const leadIdInput = document.getElementById('lead-id-input');
const leadIdFetchBtn = document.getElementById('lead-id-fetch-btn');
const leadDetailStatus = document.getElementById('lead-detail-status');
const leadDetailData = document.getElementById('lead-detail-data');

let activePanelTab = 'call';
let chatMessages = [];
let chatSending = false;
let latestSummary = null;
let latestLeadDetail = null;
let latestLeadId = null;
let latestLeadFacts = null;
let latestLeadMissingFields = null;
let leadDetailRequestId = 0;
let leadFetchInFlight = false;

async function loadStoredMessages() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'LOAD_MESSAGES' }, (response) => {
      resolve(response?.messages || []);
    });
  });
}

async function persistChatMessages() {
  await chrome.storage.local.set({ chatMessages });
}

async function persistActivePanelTab() {
  await chrome.storage.local.set({ activePanelTab });
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
  // Batch all storage reads into a single call
  const [messages, stored] = await Promise.all([
    loadStoredMessages(),
    chrome.storage.local.get([
      'chatMessages',
      'activePanelTab',
      'currentLeadDetail',
      'currentLeadId',
      'currentLeadFacts',
      'currentLeadMissingFields',
    ]),
  ]);
  // Restore chat state
  chatMessages = Array.isArray(stored.chatMessages) ? stored.chatMessages : [];
  activePanelTab = stored.activePanelTab === 'chat' ? 'chat' : 'call';

  renderStoredMessages(messages);
  renderStoredChatMessages();
  setActivePanelTab(activePanelTab, { persist: false });
  await loadStoredLeadDetail();

  chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
    if (response) {
      updateCaptureUI(response.active);
      updateAgentMicPauseUI(response.agentMicPaused, response.active);
      updateCaptureModeUI(response.captureMode);
    }
  });
}

initializePanel();

if (leadIdForm) {
  leadIdForm.addEventListener('submit', (event) => {
    event.preventDefault();
    fetchLeadDetailByInput().catch((err) => {
      updateLeadDetailStatus(`Lead detail fetch failed: ${err.message}`, 'error');
      leadFetchInFlight = false;
      if (leadIdFetchBtn) {
        leadIdFetchBtn.disabled = false;
      }
    });
  });
}

callTabBtn.addEventListener('click', () => {
  setActivePanelTab('call');
});

chatTabBtn.addEventListener('click', () => {
  setActivePanelTab('chat');
});

toggleBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'TOGGLE_CAPTURE' }, (response) => {
    if (chrome.runtime.lastError) {
      return;
    }
    if (response) {
      updateCaptureUI(response.active);
      updateAgentMicPauseUI(response.agentMicPaused, response.active);
      updateCaptureModeUI(response.captureMode);
    }
  });
});

pauseAgentBtn.addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'TOGGLE_AGENT_MIC_PAUSE' }, (response) => {
    if (chrome.runtime.lastError || !response) {
      return;
    }
    updateAgentMicPauseUI(response.agentMicPaused, response.active);
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

clearChatBtn.addEventListener('click', async () => {
  chatMessages = [];
  renderStoredChatMessages();
  await chrome.storage.local.remove(['chatMessages']);
});

chatForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  await sendChatMessage();
});

chatInput.addEventListener('keydown', async (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    await sendChatMessage();
  }
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

summaryModal.addEventListener('click', (event) => {
  if (event.target === summaryModal) {
    summaryModal.classList.remove('active');
  }
});

const micPermissionBtn = document.getElementById('mic-permission-btn');
if (micPermissionBtn) {
  micPermissionBtn.addEventListener('click', () => {
    chrome.tabs.create({ url: chrome.runtime.getURL('permission.html') });
  });
}

function updateCaptureUI(isActive) {
  toggleBtn.classList.toggle('active', Boolean(isActive));
  toggleBtn.textContent = isActive ? 'Stop Capture' : 'Start Capture';
  dot.classList.toggle('active', Boolean(isActive));
}

function updateAgentMicPauseUI(isPaused, isActive = true) {
  pauseAgentBtn.disabled = !isActive;
  pauseAgentBtn.classList.toggle('paused', Boolean(isPaused));
  pauseAgentBtn.textContent = isPaused ? 'Resume Mic' : 'Pause Mic';
}

function updateCaptureModeUI(mode) {
  const isRtcMode = mode === 'rtc';
  captureModeBtn.textContent = isRtcMode ? 'Mode: RTC' : 'Mode: Google Meet';
}

async function loadStoredLeadDetail() {
  const stored = await chrome.storage.local
    .get(['currentLeadDetail', 'currentLeadId', 'currentLeadFacts', 'currentLeadMissingFields'])
    .catch(() => ({}));

  latestLeadDetail = stored.currentLeadDetail || null;
  latestLeadId = stored.currentLeadId || null;
  latestLeadFacts = stored.currentLeadFacts || LeadDetailApi.buildLeadFacts(latestLeadDetail);
  latestLeadMissingFields = stored.currentLeadMissingFields || LeadDetailApi.buildLeadMissingFields(latestLeadDetail);

  if (leadIdInput && latestLeadId) {
    leadIdInput.value = String(latestLeadId);
  }

  if (latestLeadDetail && latestLeadId) {
    updateLeadDetailStatus(formatLeadDetailStatus(latestLeadId, latestLeadDetail, latestLeadMissingFields), 'success');
    renderLeadDetailData(latestLeadDetail);
    return;
  }

  updateLeadDetailStatus('Enter a lead id and fetch details.');
  renderLeadDetailData(null);
}

async function fetchLeadDetailByInput() {
  if (!leadIdInput || !leadDetailStatus) {
    return;
  }

  const leadId = normalizeLeadIdInput(leadIdInput.value);
  if (!leadId) {
    updateLeadDetailStatus('Enter a valid numeric lead id.', 'error');
    return;
  }

  if (leadFetchInFlight) {
    return;
  }

  const requestId = leadDetailRequestId + 1;
  leadDetailRequestId = requestId;
  leadFetchInFlight = true;
  if (leadIdFetchBtn) {
    leadIdFetchBtn.disabled = true;
  }

  updateLeadDetailStatus(`Fetching lead ${leadId} details...`, 'loading');
  renderLeadDetailData(null);

  const response = await new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'GET_LEAD_DETAIL', leadId }, (reply) => {
      resolve(reply || {});
    });
  });

  if (requestId !== leadDetailRequestId) {
    return;
  }

  leadFetchInFlight = false;
  if (leadIdFetchBtn) {
    leadIdFetchBtn.disabled = false;
  }

  if (response.error) {
    updateLeadDetailStatus(`Lead detail fetch failed: ${response.error}`, 'error');
    latestLeadDetail = null;
    latestLeadId = null;
    latestLeadFacts = null;
    latestLeadMissingFields = null;
    renderLeadDetailData(null);
    return;
  }

  latestLeadDetail = response.detail || null;
  latestLeadId = response.leadId || leadId;
  latestLeadFacts = LeadDetailApi.buildLeadFacts(latestLeadDetail);
  latestLeadMissingFields = response.missingFields || LeadDetailApi.buildLeadMissingFields(latestLeadDetail);
  if (leadIdInput) {
    leadIdInput.value = String(latestLeadId || leadId);
  }
  updateLeadDetailStatus(formatLeadDetailStatus(latestLeadId, latestLeadDetail, latestLeadMissingFields), 'success');
  renderLeadDetailData(latestLeadDetail);
}

function formatLeadDetailStatus(leadId, detail, missingFields = []) {
  const customer = detail?.customer || {};
  const leadDetails = detail?.lead_details || {};
  const customerName = [customer.first_name, customer.last_name].filter(Boolean).join(' ');
  const statusName = detail?.status_info?.statuslang?.status_name || '';
  const loanAmount = leadDetails.loan_amount || leadDetails.login_amount || leadDetails.approved_amount || '';
  const parts = [`Lead ${leadId} details loaded`];
  if (customerName) {
    parts.push(customerName);
  }
  if (statusName) {
    parts.push(statusName);
  }
  if (loanAmount) {
    parts.push(`₹${loanAmount}`);
  }
  if (Array.isArray(missingFields)) {
    parts.push(`${missingFields.length} missing/null fields`);
  }
  return parts.join(' · ');
}

function updateLeadDetailStatus(message, state = '') {
  leadDetailStatus.textContent = message;
  leadDetailStatus.classList.toggle('success', state === 'success');
  leadDetailStatus.classList.toggle('error', state === 'error');
  leadDetailStatus.classList.toggle('loading', state === 'loading');
}

function renderLeadDetailData(detail) {
  if (!leadDetailData) {
    return;
  }
  leadDetailData.innerHTML = '';
  leadDetailData.classList.toggle('active', Boolean(detail));
  if (!detail) {
    return;
  }

  const customer = detail.customer || {};
  const leadDetails = detail.lead_details || {};
  const bankName = leadDetails.bank?.banklang?.bank_name || '';
  const summary = {
    Lead: detail.id || leadDetails.lead_id || '',
    Customer: [customer.first_name, customer.last_name].filter(Boolean).join(' '),
    Mobile: customer.mobile || '',
    Email: customer.email || '',
    Status: detail.status_info?.statuslang?.status_name || '',
    Substatus: detail.sub_status_info?.substatuslang?.sub_status_name || '',
    Bank: bankName,
    Amount: leadDetails.loan_amount || leadDetails.login_amount || leadDetails.approved_amount || '',
  };

  const summaryEl = document.createElement('div');
  summaryEl.className = 'lead-detail-summary';
  for (const [key, value] of Object.entries(summary)) {
    if (!value) {
      continue;
    }
    const row = document.createElement('div');
    row.className = 'lead-detail-row';

    const keyEl = document.createElement('div');
    keyEl.className = 'lead-detail-key';
    keyEl.textContent = key;

    const valueEl = document.createElement('div');
    valueEl.className = 'lead-detail-value';
    valueEl.textContent = String(value);

    row.appendChild(keyEl);
    row.appendChild(valueEl);
    summaryEl.appendChild(row);
  }

  const rawDetails = document.createElement('details');
  rawDetails.className = 'lead-detail-json';

  const rawSummary = document.createElement('summary');
  rawSummary.textContent = 'View raw loaded data';

  const rawJson = document.createElement('pre');
  rawJson.textContent = JSON.stringify(detail, null, 2);

  rawDetails.appendChild(rawSummary);
  rawDetails.appendChild(rawJson);
  leadDetailData.appendChild(summaryEl);
  leadDetailData.appendChild(rawDetails);
}

function setActivePanelTab(tab, options = {}) {
  activePanelTab = tab === 'chat' ? 'chat' : 'call';
  callTabBtn.classList.toggle('active', activePanelTab === 'call');
  chatTabBtn.classList.toggle('active', activePanelTab === 'chat');
  callView.classList.toggle('active', activePanelTab === 'call');
  chatView.classList.toggle('active', activePanelTab === 'chat');

  if (activePanelTab === 'call') {
    scrollToBottom();
  } else {
    scrollChatToBottom();
    setTimeout(() => chatInput.focus(), 0);
  }

  if (options.persist !== false) {
    persistActivePanelTab().catch(() => {});
  }
}

function renderStoredChatMessages() {
  chatLog.innerHTML = '';
  if (!chatMessages.length) {
    const empty = document.createElement('div');
    empty.className = 'chat-empty';
    empty.textContent = 'Start a chat to ask the assistant anything.';
    chatLog.appendChild(empty);
    return;
  }

  for (const message of chatMessages) {
    chatLog.appendChild(
      createChatMessageElement(message.role, message.content, false, message.details, message.actions).element,
    );
  }
  scrollChatToBottom();
}

function createChatMessageElement(role, content, loading = false, details = null, actions = null) {
  const el = document.createElement('div');
  el.className = `chat-message ${role === 'user' ? 'user' : 'assistant'}`;
  if (loading) {
    el.classList.add('loading');
  }

  const label = document.createElement('div');
  label.className = 'chat-role';
  label.textContent = role === 'user' ? 'You' : 'Assistant';

  const text = document.createElement('div');
  text.className = 'chat-text';
  text.textContent = content || '';

  el.appendChild(label);
  el.appendChild(text);

  if (details && typeof details === 'object' && Object.keys(details).length > 0) {
    el.appendChild(createKeyValueCard(details));
  }

  if (actions?.type === 'lead_refresh_confirmation') {
    el.appendChild(createLeadRefreshActions());
  }

  return { element: el, text };
}

function createLeadRefreshActions() {
  const actionsEl = document.createElement('div');
  actionsEl.className = 'chat-actions';

  const yesBtn = document.createElement('button');
  yesBtn.type = 'button';
  yesBtn.className = 'chat-action-btn primary';
  yesBtn.textContent = 'Yes, refresh';
  yesBtn.addEventListener('click', () => {
    disableActionButtons(actionsEl);
    resolveLeadRefreshActions(actionsEl).catch(() => {});
    handleLeadRefreshConfirmation(true).catch((err) => {
      addAssistantChatMessage(`Lead refresh failed: ${err.message}`);
    });
  });

  const noBtn = document.createElement('button');
  noBtn.type = 'button';
  noBtn.className = 'chat-action-btn';
  noBtn.textContent = 'No, same data';
  noBtn.addEventListener('click', () => {
    disableActionButtons(actionsEl);
    resolveLeadRefreshActions(actionsEl).catch(() => {});
    handleLeadRefreshConfirmation(false).catch((err) => {
      addAssistantChatMessage(`Failed to continue: ${err.message}`);
    });
  });

  actionsEl.appendChild(yesBtn);
  actionsEl.appendChild(noBtn);
  return actionsEl;
}

function disableActionButtons(container) {
  container.querySelectorAll('button').forEach((button) => {
    button.disabled = true;
  });
}

async function resolveLeadRefreshActions(container) {
  container.remove();
  for (let index = chatMessages.length - 1; index >= 0; index -= 1) {
    const message = chatMessages[index];
    if (message?.actions?.type === 'lead_refresh_confirmation') {
      message.actions = null;
      break;
    }
  }
  await persistChatMessages().catch(() => {});
}

function createKeyValueCard(details) {
  const card = document.createElement('div');
  card.className = 'chat-kv-card';

  for (const [key, value] of Object.entries(details)) {
    const row = document.createElement('div');
    row.className = 'chat-kv-row';

    const keyEl = document.createElement('div');
    keyEl.className = 'chat-kv-key';
    keyEl.textContent = key;

    const valueEl = document.createElement('div');
    valueEl.className = 'chat-kv-value';
    valueEl.textContent = String(value);

    row.appendChild(keyEl);
    row.appendChild(valueEl);
    card.appendChild(row);
  }

  return card;
}

function scrollChatToBottom() {
  chatLog.scrollTop = chatLog.scrollHeight;
}

async function addAssistantChatMessage(content, actions = null) {
  chatMessages.push({
    role: 'assistant',
    content,
    timestamp: Date.now(),
    actions,
  });
  chatLog.innerHTML = '';
  renderStoredChatMessages();
  await persistChatMessages().catch(() => {});
}

async function handleLeadRefreshConfirmation(shouldRefresh) {
  if (!shouldRefresh) {
    await sendChatMessage('No, same data');
    return;
  }

  const leadId = latestLeadId || normalizeLeadIdInput(leadIdInput?.value);
  if (!leadId) {
    throw new Error('Lead id is required to refresh lead data.');
  }

  updateLeadDetailStatus(`Refreshing lead ${leadId} details...`, 'loading');
  const response = await new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'GET_LEAD_DETAIL', leadId }, (reply) => {
      resolve(reply || {});
    });
  });
  if (response.error) {
    throw new Error(response.error);
  }

  latestLeadDetail = response.detail || null;
  latestLeadId = response.leadId || leadId;
  latestLeadFacts = LeadDetailApi.buildLeadFacts(latestLeadDetail);
  latestLeadMissingFields = response.missingFields || LeadDetailApi.buildLeadMissingFields(latestLeadDetail);
  updateLeadDetailStatus(formatLeadDetailStatus(latestLeadId, latestLeadDetail, latestLeadMissingFields), 'success');
  renderLeadDetailData(latestLeadDetail);

  await sendChatMessage('Yes, refreshed latest lead data. What is the next step?', { leadRefreshed: true });
}

async function sendChatMessage(textOverride = null, options = {}) {
  if (chatSending) {
    return;
  }

  const text = (textOverride ?? chatInput.value).trim();
  if (!text) {
    return;
  }

  if (textOverride === null) {
    chatInput.value = '';
  }
  const userMessage = { role: 'user', content: text, timestamp: Date.now() };
  chatMessages.push(userMessage);
  chatLog.innerHTML = '';
  renderStoredChatMessages();
  await persistChatMessages().catch(() => {});

  const assistantBubble = createChatMessageElement('assistant', 'Thinking...', true);
  chatLog.appendChild(assistantBubble.element);
  scrollChatToBottom();

  chatSending = true;
  chatSendBtn.disabled = true;

  try {
    const history = chatMessages.map((item) => ({
      role: item.role,
      content: item.content,
    }));
    const storedLead = await chrome.storage.local
      .get(['currentLeadDetail', 'currentLeadId'])
      .catch(() => ({}));
    const leadDetailForChat = latestLeadDetail || storedLead.currentLeadDetail || null;
    const leadIdForChat = latestLeadId || storedLead.currentLeadId || normalizeLeadIdInput(leadIdInput?.value) || null;
    const chatPayload = {
      type: 'CHAT_SEND',
      message: text,
      history,
      lead_id: leadIdForChat,
      lead_refreshed: Boolean(options.leadRefreshed),
    };

    if (leadDetailForChat) {
      chatPayload.lead_detail = leadDetailForChat;
      chatPayload.lead_facts = LeadDetailApi.buildLeadFacts(leadDetailForChat);
      chatPayload.lead_missing_fields = LeadDetailApi.buildLeadMissingFields(leadDetailForChat);
    }

    console.group('[LeadDebug][sidepanel] chat payload');
    console.log('lead_id', chatPayload.lead_id);
    console.log('has lead_detail', Boolean(chatPayload.lead_detail));
    console.log('lead_detail keys', chatPayload.lead_detail ? Object.keys(chatPayload.lead_detail).slice(0, 30) : []);
    console.log('lead_facts count', chatPayload.lead_facts ? Object.keys(chatPayload.lead_facts).length : 0);
    console.log('lead_facts sample', chatPayload.lead_facts ? Object.fromEntries(Object.entries(chatPayload.lead_facts).slice(0, 30)) : {});
    console.log('lead_missing_fields count', Array.isArray(chatPayload.lead_missing_fields) ? chatPayload.lead_missing_fields.length : 0);
    console.log('lead_missing_fields sample', Array.isArray(chatPayload.lead_missing_fields) ? chatPayload.lead_missing_fields.slice(0, 30) : []);
    console.groupEnd();

    const response = await new Promise((resolve) => {
      chrome.runtime.sendMessage(chatPayload, (reply) => resolve(reply));
    });

    const replyText = response?.reply?.reply || response?.reply || response?.text || '';
    if (!replyText) {
      throw new Error(response?.error || 'Empty reply');
    }

    assistantBubble.element.classList.remove('loading');
    assistantBubble.text.textContent = replyText;
    const actions = response?.needs_lead_refresh_confirmation ? { type: 'lead_refresh_confirmation' } : null;
    if (actions) {
      assistantBubble.element.appendChild(createLeadRefreshActions());
    }
    chatMessages.push({
      role: 'assistant',
      content: replyText,
      timestamp: Date.now(),
      actions,
    });
    await persistChatMessages().catch(() => {});
  } catch (err) {
    assistantBubble.element.classList.add('loading');
    assistantBubble.text.textContent = `Failed to get chat reply: ${err.message}`;
  } finally {
    chatSending = false;
    chatSendBtn.disabled = false;
    scrollChatToBottom();
  }
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
      && now - pendingMergeAt <= CONFIG.UTTERANCE_MERGE_WINDOW_MS;

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

  CAPTURE_STATUS_CHANGED(message) {
    updateCaptureUI(message.active);
    updateAgentMicPauseUI(message.agentMicPaused, message.active);
  },
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

function buildSummaryFieldMessage(customerInfo) {
  const entries = Object.entries(customerInfo || {});
  if (!entries.length) {
    return 'No extracted fields were found.';
  }

  const lines = entries.map(([key, value]) => `${key}: ${value}`);
  return `Extracted fields ready for database review:\n${lines.join('\n')}`;
}

async function sendSummaryToChat() {
  const customerInfo = latestSummary?.customer_info || {};
  const entries = Object.entries(customerInfo);

  if (!entries.length) {
    alert('No extracted fields available to send to chat.');
    return;
  }

  setActivePanelTab('chat');
  summaryModal.classList.remove('active');

  const userText = buildSummaryFieldMessage(customerInfo);
  chatMessages.push({
    role: 'user',
    content: userText,
    timestamp: Date.now(),
  });
  renderStoredChatMessages();
  await persistChatMessages().catch(() => {});

  const assistantBubble = createChatMessageElement('assistant', 'Thinking...', true);
  chatLog.appendChild(assistantBubble.element);
  scrollChatToBottom();

  chatSending = true;
  chatSendBtn.disabled = true;

  try {
    const response = await new Promise((resolve) => {
      chrome.runtime.sendMessage(
        {
          type: 'SUMMARY_CHAT_SEND',
          customerInfo,
          conversation: userText,
        },
        (reply) => resolve(reply),
      );
    });

    const replyText = response?.reply || response?.error || '';
    const filteredCustomerInfo = response?.customer_info || {};
    if (!replyText && Object.keys(filteredCustomerInfo).length === 0) {
      throw new Error('Empty reply');
    }

    assistantBubble.element.classList.remove('loading');
    assistantBubble.text.textContent = replyText || 'Filtered data ready for insertion.';
    if (Object.keys(filteredCustomerInfo).length > 0) {
      assistantBubble.element.appendChild(createKeyValueCard(filteredCustomerInfo));
    }
    chatMessages.push({
      role: 'assistant',
      content: assistantBubble.text.textContent,
      details: filteredCustomerInfo,
      timestamp: Date.now(),
    });
    await persistChatMessages().catch(() => {});
  } catch (err) {
    assistantBubble.element.classList.add('loading');
    assistantBubble.text.textContent = `Failed to prepare database question: ${err.message}`;
  } finally {
    chatSending = false;
    chatSendBtn.disabled = false;
    scrollChatToBottom();
  }
}

function displaySummary(summary) {
  latestSummary = summary || null;
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
      <div class="summary-actions">
        <button id="summary-send-btn" class="summary-secondary-btn" type="button">
          Send to Chat
        </button>
        <div class="summary-actions-note">
          Returns the recommended extracted field(s) to insert into the database.
        </div>
      </div>
    `;
    const button = document.getElementById('summary-send-btn');
    if (button) {
      button.onclick = () => {
        sendSummaryToChat().catch((err) => {
          alert(`Failed to send summary to chat: ${err.message}`);
        });
      };
    }
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
      <div class="summary-actions">
        <button id="summary-send-btn" class="summary-secondary-btn" type="button">
          Send to Chat
        </button>
        <div class="summary-actions-note">
          Returns the recommended extracted field(s) to insert into the database.
        </div>
      </div>
  `;
  const button = document.getElementById('summary-send-btn');
  if (button) {
    button.onclick = () => {
      sendSummaryToChat().catch((err) => {
        alert(`Failed to send summary to chat: ${err.message}`);
      });
    };
  }
  summaryModal.classList.add('active');
}

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}
