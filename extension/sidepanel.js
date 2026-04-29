// sidepanel.js — Native Side Panel Logic

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
const currentTabUrl = document.getElementById('current-tab-url');
const currentTabUrlText = document.getElementById('current-tab-url-text');
const leadDetailStatus = document.getElementById('lead-detail-status');
const leadDetailData = document.getElementById('lead-detail-data');

let activePanelTab = 'call';
let chatMessages = [];
let chatSending = false;
let latestSummary = null;
let latestLeadDetail = null;
let latestLeadId = null;
let latestLeadFacts = null;
let leadDetailLookupTimer = null;
let leadDetailRequestId = 0;
let lastLeadLookupKey = '';
let leadLookupInFlightKey = '';

async function loadStoredMessages() {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'LOAD_MESSAGES' }, (response) => {
      resolve(response?.messages || []);
    });
  });
}

async function loadStoredChatMessages() {
  const result = await chrome.storage.local.get(['chatMessages', 'activePanelTab']);
  chatMessages = Array.isArray(result.chatMessages) ? result.chatMessages : [];
  activePanelTab = result.activePanelTab === 'chat' ? 'chat' : 'call';
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
  const [messages] = await Promise.all([
    loadStoredMessages(),
    loadStoredChatMessages(),
    refreshCurrentTabUrl(),
  ]);
  renderStoredMessages(messages);
  renderStoredChatMessages();
  setActivePanelTab(activePanelTab, { persist: false });

  chrome.runtime.sendMessage({ type: 'GET_STATUS' }, (response) => {
    if (response) {
      updateCaptureUI(response.active);
      updateAgentMicPauseUI(response.agentMicPaused, response.active);
      updateCaptureModeUI(response.captureMode);
    }
  });
}

initializePanel();

chrome.tabs.onActivated.addListener(() => {
  refreshCurrentTabUrl();
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.url) {
    refreshCurrentTabUrl();
  }
});

chrome.windows.onFocusChanged.addListener((windowId) => {
  if (windowId !== chrome.windows.WINDOW_ID_NONE) {
    refreshCurrentTabUrl();
  }
});

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

function updateAgentMicPauseUI(isPaused, isActive = true) {
  pauseAgentBtn.disabled = !isActive;
  pauseAgentBtn.classList.toggle('paused', Boolean(isPaused));
  pauseAgentBtn.textContent = isPaused ? 'Resume Mic' : 'Pause Mic';
}

function updateCaptureModeUI(mode) {
  const isRtcMode = mode === 'rtc';
  captureModeBtn.textContent = isRtcMode ? 'Mode: RTC' : 'Mode: Google Meet';
}

async function refreshCurrentTabUrl() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const url = tab?.url || tab?.pendingUrl || '';
    updateCurrentTabUrl(url);
  } catch (err) {
    updateCurrentTabUrl('');
  }
}

function updateCurrentTabUrl(url) {
  if (!currentTabUrlText || !currentTabUrl) {
    return;
  }

  const displayUrl = url || 'Current tab URL unavailable';
  currentTabUrlText.textContent = displayUrl;
  currentTabUrl.title = displayUrl;
  scheduleLeadDetailLookup(url);
}

function buildLeadLookupKey(url) {
  if (!url || !LeadDetailApi.isLoanDetailUrl(url)) {
    return '';
  }
  const leadId = LeadDetailApi.extractLeadIdFromUrl(url) || '';
  try {
    const parsedUrl = new URL(url);
    return `${parsedUrl.origin}${parsedUrl.pathname}?lead_id=${leadId}`;
  } catch (err) {
    return url;
  }
}

function scheduleLeadDetailLookup(url) {
  if (!leadDetailStatus) {
    return;
  }

  const lookupKey = buildLeadLookupKey(url);
  if (lookupKey && (lookupKey === lastLeadLookupKey || lookupKey === leadLookupInFlightKey)) {
    return;
  }

  clearTimeout(leadDetailLookupTimer);
  leadDetailLookupTimer = setTimeout(() => {
    refreshLeadDetailStatus(url).catch(() => {});
  }, 250);
}

async function refreshLeadDetailStatus(url) {
  const requestId = leadDetailRequestId + 1;
  leadDetailRequestId = requestId;
  const lookupKey = buildLeadLookupKey(url);

  if (!url || !LeadDetailApi.isLoanDetailUrl(url)) {
    lastLeadLookupKey = '';
    leadLookupInFlightKey = '';
    updateLeadDetailStatus('Lead detail check will run on Ambak lead pages.');
    latestLeadDetail = null;
    latestLeadId = null;
    latestLeadFacts = null;
    renderLeadDetailData(null);
    return;
  }

  if (lookupKey && (lookupKey === lastLeadLookupKey || lookupKey === leadLookupInFlightKey)) {
    return;
  }

  leadLookupInFlightKey = lookupKey;

  updateLeadDetailStatus('Checking lead details from API...', 'loading');
  renderLeadDetailData(null);
  const response = await new Promise((resolve) => {
    chrome.runtime.sendMessage({ type: 'GET_LEAD_DETAIL', url }, (reply) => {
      resolve(reply || {});
    });
  });

  if (requestId !== leadDetailRequestId) {
    return;
  }

  if (response.error) {
    leadLookupInFlightKey = '';
    updateLeadDetailStatus(`Lead detail API check failed: ${response.error}`, 'error');
    latestLeadDetail = null;
    latestLeadId = null;
    latestLeadFacts = null;
    renderLeadDetailData(null);
    return;
  }
  if (response.skipped) {
    leadLookupInFlightKey = '';
    updateLeadDetailStatus(response.reason || 'Lead detail check skipped.');
    latestLeadDetail = null;
    latestLeadId = null;
    latestLeadFacts = null;
    renderLeadDetailData(null);
    return;
  }

  latestLeadDetail = response.detail || null;
  latestLeadId = response.leadId || null;
  latestLeadFacts = LeadDetailApi.buildLeadFacts(latestLeadDetail);
  lastLeadLookupKey = lookupKey || buildLeadLookupKey(url);
  leadLookupInFlightKey = '';
  updateLeadDetailStatus(formatLeadDetailStatus(response.leadId, response.detail), 'success');
  renderLeadDetailData(response.detail, response.dreDocuments || null, response.dreDocumentError || '');
}

function formatLeadDetailStatus(leadId, detail) {
  const leadRecord = LeadDetailApi.getPrimaryLeadDetail(detail);
  const customer = leadRecord?.customer || {};
  const leadDetails = leadRecord?.lead_details || {};
  const customerName = [customer.first_name, customer.last_name].filter(Boolean).join(' ');
  const statusName = leadRecord?.status_info?.statuslang?.status_name || '';
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
  return parts.join(' · ');
}

function updateLeadDetailStatus(message, state = '') {
  leadDetailStatus.textContent = message;
  leadDetailStatus.classList.toggle('success', state === 'success');
  leadDetailStatus.classList.toggle('error', state === 'error');
  leadDetailStatus.classList.toggle('loading', state === 'loading');
}

function toFlagText(value) {
  if (value === 1 || value === '1' || value === true) {
    return 'Executed';
  }
  if (value === 0 || value === '0' || value === false) {
    return 'Not executed';
  }
  return '';
}

function getDreStatus(detail) {
  const leadRecord = LeadDetailApi.getPrimaryLeadDetail(detail);
  return toFlagText(leadRecord?.customer?.dre_executed)
    || toFlagText(leadRecord?.lead_details?.dre_executed)
    || toFlagText(Array.isArray(leadRecord?.co_applicant) ? leadRecord.co_applicant.find((item) => item?.dre_executed !== undefined)?.dre_executed : undefined);
}

function isDocLike(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return false;
  }
  return ['doc_id', 'ldoc_id', 'parent_doc_id', 'doc_path', 'child_name', 'parent_name', 'is_doc_uploaded', 'doc_upload_url'].some((key) => key in value);
}

function parsePossibleJson(value) {
  if (typeof value !== 'string') {
    return null;
  }
  const trimmed = value.trim();
  if (!trimmed || !/^[{[]/.test(trimmed)) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch (err) {
    return null;
  }
}

function collectDocItems(value, items = []) {
  if (!value) {
    return items;
  }
  const parsed = parsePossibleJson(value);
  if (parsed) {
    return collectDocItems(parsed, items);
  }
  if (Array.isArray(value)) {
    value.forEach((item) => collectDocItems(item, items));
    return items;
  }
  if (typeof value !== 'object') {
    return items;
  }
  if (isDocLike(value)) {
    items.push(value);
  }
  Object.values(value).forEach((nestedValue) => collectDocItems(nestedValue, items));
  return items;
}

function getDocName(doc) {
  return doc.child_name
    || doc.parent_name
    || doc.document_name
    || doc.doc_name
    || doc.label
    || (doc.doc_id ? `Document ${doc.doc_id}` : 'Document');
}

function isDocumentUploaded(doc) {
  if ('is_doc_uploaded' in doc) {
    return doc.is_doc_uploaded === 1 || doc.is_doc_uploaded === '1' || doc.is_doc_uploaded === true;
  }
  if (doc.doc_upload_url || doc.doc_path) {
    return true;
  }
  const status = String(doc.status || '').toLowerCase();
  return ['uploaded', 'approved', 'verified', 'complete', 'completed'].some((term) => status.includes(term));
}

function buildDocumentBuckets(detail, dreDocuments) {
  const leadRecord = LeadDetailApi.getPrimaryLeadDetail(detail);
  const docs = [
    ...collectDocItems(dreDocuments),
    ...collectDocItems(leadRecord?.customer?.recommended_docs),
  ];
  const seen = new Set();
  const buckets = { uploaded: [], pending: [] };

  docs.forEach((doc) => {
    const name = getDocName(doc);
    const key = [doc.id, doc.ldoc_id, doc.doc_id, doc.parent_doc_id, doc.customer_id, name].filter(Boolean).join(':');
    if (seen.has(key)) {
      return;
    }
    seen.add(key);
    buckets[isDocumentUploaded(doc) ? 'uploaded' : 'pending'].push({
      name,
      parentName: doc.parent_name || '',
      status: doc.status || '',
      path: doc.doc_path || doc.doc_upload_url || '',
    });
  });

  return buckets;
}

function appendDocumentList(parent, title, docs, state) {
  const section = document.createElement('div');
  section.className = 'lead-document-group';

  const heading = document.createElement('div');
  heading.className = 'lead-document-heading';
  heading.textContent = `${title} (${docs.length})`;
  section.appendChild(heading);

  if (!docs.length) {
    const empty = document.createElement('div');
    empty.className = 'lead-document-empty';
    empty.textContent = 'None';
    section.appendChild(empty);
  } else {
    docs.forEach((doc) => {
      const row = document.createElement('div');
      row.className = `lead-document-item ${state}`;
      const dot = document.createElement('span');
      dot.className = 'lead-document-dot';
      const label = document.createElement('span');
      label.textContent = doc.parentName && doc.parentName !== doc.name ? `${doc.parentName} - ${doc.name}` : doc.name;
      row.appendChild(dot);
      row.appendChild(label);
      section.appendChild(row);
    });
  }

  parent.appendChild(section);
}

function renderLeadDetailData(detail, dreDocuments = null, dreDocumentError = '') {
  if (!leadDetailData) {
    return;
  }
  leadDetailData.innerHTML = '';
  leadDetailData.classList.toggle('active', Boolean(detail));
  if (!detail) {
    return;
  }

  const leadRecord = LeadDetailApi.getPrimaryLeadDetail(detail);
  const customer = leadRecord?.customer || {};
  const leadDetails = leadRecord?.lead_details || {};
  const bankName = leadDetails.bank?.banklang?.bank_name || '';
  const dreStatus = getDreStatus(detail);
  const summary = {
    Lead: leadRecord?.id || leadDetails.lead_id || '',
    Customer: [customer.first_name, customer.last_name].filter(Boolean).join(' '),
    Mobile: customer.mobile || '',
    Email: customer.email || '',
    Status: leadRecord?.status_info?.statuslang?.status_name || '',
    Substatus: leadRecord?.sub_status_info?.substatuslang?.sub_status_name || '',
    Bank: bankName,
    Amount: leadDetails.loan_amount || leadDetails.login_amount || leadDetails.approved_amount || '',
    DRE: dreStatus,
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
  rawJson.textContent = JSON.stringify({ lead_detail: detail, dre_documents: dreDocuments }, null, 2);

  const docBuckets = buildDocumentBuckets(detail, dreDocuments);
  const documentsEl = document.createElement('div');
  documentsEl.className = 'lead-document-section';

  const documentsTitle = document.createElement('div');
  documentsTitle.className = 'lead-document-title';
  documentsTitle.textContent = 'DRE Documents';
  documentsEl.appendChild(documentsTitle);

  if (dreDocumentError) {
    const error = document.createElement('div');
    error.className = 'lead-document-error';
    error.textContent = dreDocumentError;
    documentsEl.appendChild(error);
  }

  appendDocumentList(documentsEl, 'Uploaded', docBuckets.uploaded, 'uploaded');
  appendDocumentList(documentsEl, 'Pending', docBuckets.pending, 'pending');

  rawDetails.appendChild(rawSummary);
  rawDetails.appendChild(rawJson);
  leadDetailData.appendChild(summaryEl);
  leadDetailData.appendChild(documentsEl);
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
      createChatMessageElement(message.role, message.content, false, message.details).element,
    );
  }
  scrollChatToBottom();
}

function createChatMessageElement(role, content, loading = false, details = null) {
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

  return { element: el, text };
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

async function sendChatMessage() {
  if (chatSending) {
    return;
  }

  const text = chatInput.value.trim();
  if (!text) {
    return;
  }

  chatInput.value = '';
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
      .get([
        'currentLeadDetail',
        'currentLeadId',
        'currentLeadFacts',
        'currentLeadDreDocuments',
        'currentLeadDreDocumentError',
      ])
      .catch(() => ({}));
    const leadDetailForChat = latestLeadDetail || storedLead.currentLeadDetail || null;
    const leadFactsForChat = latestLeadFacts || storedLead.currentLeadFacts || LeadDetailApi.buildLeadFacts(leadDetailForChat);

    const response = await new Promise((resolve) => {
      chrome.runtime.sendMessage(
        {
          type: 'CHAT_SEND',
          message: text,
          history,
          lead_id: latestLeadId || storedLead.currentLeadId || null,
          lead_detail: leadDetailForChat,
          lead_facts: leadFactsForChat,
          lead_dre_documents: storedLead.currentLeadDreDocuments || null,
          lead_dre_document_error: storedLead.currentLeadDreDocumentError || null,
        },
        (reply) => resolve(reply),
      );
    });

    const replyText = response?.reply?.reply || response?.reply || response?.text || '';
    if (!replyText) {
      throw new Error(response?.error || 'Empty reply');
    }

    assistantBubble.element.classList.remove('loading');
    assistantBubble.text.textContent = replyText;
    chatMessages.push({
      role: 'assistant',
      content: replyText,
      timestamp: Date.now(),
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
