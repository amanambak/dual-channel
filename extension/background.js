// background.js — Service Worker (MV3)
// Orchestrates capture state, UI messages, and storage.

importScripts('config.js', 'lead-detail-api.js');

let isCapturing = false;
let isAgentMicPaused = false;
let targetTabId = null;
let currentSessionId = null;
let captureMode = 'gmeet';

function pushLeadContextToOffscreen({ leadId, facts, missingFields }) {
  chrome.runtime.sendMessage({
    type: 'SET_SESSION_LEAD_CONTEXT',
    offscreen: true,
    leadId: leadId || null,
    leadFacts: facts || null,
    leadMissingFields: missingFields || null,
  }).catch(() => {});
}

async function setCurrentSessionId(sessionId) {
  currentSessionId = sessionId || null;
  await chrome.storage.local.set({ currentSessionId });
}

async function getCurrentSessionId() {
  if (currentSessionId) {
    return currentSessionId;
  }
  const result = await chrome.storage.local.get(['currentSessionId']);
  currentSessionId = result.currentSessionId || null;
  return currentSessionId;
}

async function saveMessage(message) {
  const result = await chrome.storage.local.get(['messages']);
  const messages = result.messages || [];
  messages.push({
    ...message,
    timestamp: Date.now()
  });
  if (messages.length > 1000) {
    messages.splice(0, messages.length - 1000);
  }
  await chrome.storage.local.set({ messages });
}

async function getMessages() {
  const result = await chrome.storage.local.get(['messages']);
  return result.messages || [];
}

async function clearMessages() {
  await chrome.storage.local.remove(['messages']);
}

chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== 'toggle-capture') {
    return;
  }

  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab) {
    await chrome.sidePanel.open({ tabId: tab.id });
    handleToggleCapture();
  }
});

// Restore persisted state on service-worker startup (single read is cheaper).
chrome.storage.local.get(['isCapturing', 'isAgentMicPaused', 'currentSessionId', 'captureMode'], (result) => {
  isCapturing = result.isCapturing || false;
  isAgentMicPaused = result.isAgentMicPaused || false;
  currentSessionId = result.currentSessionId || null;
  captureMode = result.captureMode === 'rtc' ? 'rtc' : 'gmeet';
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({
    isCapturing: false,
    isAgentMicPaused: false,
    messages: [],
    currentSessionId: null,
    captureMode: 'gmeet',
    currentLeadContext: null,
    currentLeadDocumentStatus: null,
    currentLeadDreDocuments: null,
    currentLeadDreDocumentError: null
  });
  isCapturing = false;
  isAgentMicPaused = false;
  captureMode = 'gmeet';

  chrome.contextMenus.create({
    id: 'start-capture-context',
    title: 'Start Audio AI Capture',
    contexts: ['page', 'video', 'audio']
  });
});

chrome.contextMenus.onClicked.addListener((info) => {
  if (info.menuItemId === 'start-capture-context') {
    startCapture();
  }
});

// ---------------------------------------------------------------------------
// onMessage router — maps message.type -> handler function
// Add new message types here instead of extending the if-chain.
// ---------------------------------------------------------------------------

function handleGetStatus(message, sender, sendResponse) {
  getCurrentSessionId().then((sessionId) => {
    sendResponse({ active: isCapturing, agentMicPaused: isAgentMicPaused, sessionId, captureMode });
  });
  return true;
}

function handleToggleCapture(message, sender, sendResponse) {
  handleToggleCapture_internal().then((active) => {
    sendResponse({ active, agentMicPaused: isAgentMicPaused, sessionId: currentSessionId, captureMode });
  });
  return true;
}

function handleToggleAgentMicPause(message, sender, sendResponse) {
  if (!isCapturing) {
    isAgentMicPaused = false;
    chrome.storage.local.set({ isAgentMicPaused }).then(() => {
      sendResponse({ success: false, active: false, agentMicPaused: false });
    });
    return true;
  }

  isAgentMicPaused = !isAgentMicPaused;
  chrome.storage.local.set({ isAgentMicPaused }).then(() => {
    chrome.runtime.sendMessage({
      type: 'SET_AGENT_MIC_PAUSED',
      paused: isAgentMicPaused,
      offscreen: true
    }).catch(() => {});
    chrome.runtime.sendMessage({
      type: 'CAPTURE_STATUS_CHANGED',
      active: isCapturing,
      agentMicPaused: isAgentMicPaused
    }).catch(() => {});
    sendResponse({ success: true, active: isCapturing, agentMicPaused: isAgentMicPaused });
  });
  return true;
}

function handleToggleCaptureMode(message, sender, sendResponse) {
  if (isCapturing) {
    sendResponse({ success: false, captureMode, error: 'Stop capture before switching mode.' });
    return false;
  }
  captureMode = captureMode === 'rtc' ? 'gmeet' : 'rtc';
  chrome.storage.local.set({ captureMode }).then(() => {
    chrome.runtime.sendMessage({ type: 'CAPTURE_MODE_CHANGED', captureMode }).catch(() => {});
    sendResponse({ success: true, captureMode });
  });
  return true;
}

function handleLoadMessages(message, sender, sendResponse) {
  getMessages().then((messages) => sendResponse({ messages }));
  return true;
}

function handleClearMessages(message, sender, sendResponse) {
  clearMessages().then(() => sendResponse({ success: true }));
  return true;
}

function handleGenerateSummary(message, sender, sendResponse) {
  getMessages().then(async (messages) => {
    const conversation = messages.map((msg) => {
      const speaker = msg.type === 'user' ? 'Customer' : 'Caller Assist';
      return `${speaker}: ${msg.text}`;
    }).join('\n\n');

    if (!conversation.trim()) {
      sendResponse({ summary: { summary: 'Abhi tak conversation data available nahin hai.' } });
      return;
    }

    const sessionId = await getCurrentSessionId();
    const sessionUrl = sessionId
      ? `${CONFIG.BACKEND_HTTP_URL}/api/sessions/${sessionId}/summary`
      : `${CONFIG.BACKEND_HTTP_URL}/api/summary`;

    const requestInit = sessionId
      ? { method: 'GET' }
      : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conversation }) };

    try {
      let response = await fetch(sessionUrl, requestInit);
      if (!response.ok && sessionId) {
        response = await fetch(`${CONFIG.BACKEND_HTTP_URL}/api/summary`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ conversation })
        });
      }
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      sendResponse({ summary: await response.json() });
    } catch (err) {
      sendResponse({ summary: { summary: `Failed to generate summary: ${err.message}` } });
    }
  });
  return true;
}

function handleSummaryChat(message, sender, sendResponse) {
  const payload = {
    customer_info: message.customerInfo || {},
    conversation: message.conversation || '',
  };

  fetch(`${CONFIG.BACKEND_HTTP_URL}/api/summary/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      sendResponse({ reply: data.reply || '', customer_info: data.customer_info || {} });
    })
    .catch((err) => {
      sendResponse({ error: err.message });
    });
  return true;
}

function hasObjectFields(value) {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0);
}

function isAmbakTabUrl(rawUrl) {
  try {
    const url = new URL(rawUrl || '');
    return url.hostname === 'ambak.com' || url.hostname.endsWith('.ambak.com');
  } catch (err) {
    return false;
  }
}

function maskAuthTokenForLog(token) {
  const text = String(token || '').trim();
  if (!text) {
    return null;
  }
  if (text.length <= 14) {
    return `${text.slice(0, 3)}...${text.slice(-2)}`;
  }
  return `${text.slice(0, 8)}...${text.slice(-6)}`;
}

function getPageAccessToken(pageContext) {
  return pageContext?.accessToken || pageContext?.token || '';
}

async function getAmbakAuthContext() {
  const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const candidateTabs = [];
  if (activeTab?.id && isAmbakTabUrl(activeTab.url || activeTab.pendingUrl)) {
    candidateTabs.push(activeTab);
  }

  const ambakTabs = await chrome.tabs.query({ url: ['https://*.ambak.com/*', 'http://*.ambak.com/*'] }).catch(() => []);
  for (const tab of ambakTabs) {
    if (tab?.id && !candidateTabs.some((candidate) => candidate.id === tab.id)) {
      candidateTabs.push(tab);
    }
  }

  for (const tab of candidateTabs) {
    try {
      await ensureContentScriptInjected(tab.id);
      const pageContext = await chrome.tabs.sendMessage(tab.id, { type: 'GET_AMBAK_PAGE_CONTEXT' });
      if (pageContext?.token) {
        return { tab, pageContext };
      }
    } catch (err) {
    }
  }

  throw new Error('Open any Ambak page where you are logged in so the auth token can be read.');
}

async function fetchCustomerDreDocuments({ detail, leadId, token }) {
  const leadRecord = LeadDetailApi.getPrimaryLeadDetail
    ? LeadDetailApi.getPrimaryLeadDetail(detail)
    : detail;
  const customerId = leadRecord?.customer?.customer_id;
  if (!customerId) {
    return { dreDocuments: null, error: 'Customer ID was not found in lead details.' };
  }

  try {
    const result = await LeadDetailApi.fetchLeadDreDocuments({
      leadId,
      token,
      type: 'customer',
      customerId,
    });
    if (!result.documents) {
      return { dreDocuments: null, error: 'DRE document API returned no document data.' };
    }
    return { dreDocuments: result.documents || null, error: null };
  } catch (err) {
    return { dreDocuments: null, error: err.message };
  }
}

async function buildBackendLeadContext({
  leadId,
  detail,
  dreDocuments = null,
  dreDocumentError = null,
  leadDocumentStatus = null,
  leadFacts = null,
}) {
  const response = await fetch(`${CONFIG.BACKEND_HTTP_URL}/api/lead/context`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      lead_id: leadId || null,
      lead_detail: detail || null,
      lead_dre_documents: dreDocuments || null,
      lead_dre_document_error: dreDocumentError || null,
      lead_document_status: leadDocumentStatus || null,
      lead_facts: leadFacts || null,
    })
  });
  if (!response.ok) {
    throw new Error(`Lead context API failed with HTTP ${response.status}`);
  }
  return response.json();
}

async function persistLeadContext({ detail, leadId, facts, missingFields, dreDocuments, dreDocumentError, leadContext }) {
  await chrome.storage.local.set({
    currentLeadDetail: detail || null,
    currentLeadId: leadId || leadContext?.lead_id || null,
    currentLeadFacts: facts || leadContext?.facts || null,
    currentLeadMissingFields: missingFields || null,
    currentLeadContext: leadContext || null,
    currentLeadDocumentStatus: leadContext?.document_status || null,
    currentLeadDreDocuments: dreDocuments || null,
    currentLeadDreDocumentError: leadContext?.document_error || dreDocumentError || null,
  });
}

async function fetchAndStoreLeadDetail(leadId) {
  const normalizedLeadId = LeadDetailApi.normalizeLeadId ? LeadDetailApi.normalizeLeadId(leadId) : String(leadId || '').trim();
  if (!/^\d+$/.test(normalizedLeadId)) {
    throw new Error('Valid numeric lead id is required.');
  }

  const { pageContext } = await getAmbakAuthContext();
  const accessToken = getPageAccessToken(pageContext);
  console.log('[LeadDebug][background] fetching lead detail', {
    leadId: normalizedLeadId,
    'auth token found': Boolean(accessToken),
    'auth token preview': maskAuthTokenForLog(accessToken),
  });
  const result = await LeadDetailApi.fetchLeadDetail({ leadId: normalizedLeadId, token: accessToken });
  const facts = LeadDetailApi.buildLeadFacts(result.detail);
  const missingFields = LeadDetailApi.buildLeadMissingFields(result.detail);
  const dreResult = await fetchCustomerDreDocuments({
    detail: result.detail,
    leadId: result.leadId,
    token: accessToken,
  });
  const leadContext = await buildBackendLeadContext({
    leadId: result.leadId,
    detail: result.detail,
    dreDocuments: dreResult.dreDocuments,
    dreDocumentError: dreResult.error,
    leadFacts: facts,
  });
  console.group('[LeadDebug][background] fetched lead detail');
  console.log('leadId', result.leadId);
  console.log('detail keys', result.detail ? Object.keys(result.detail).slice(0, 30) : []);
  console.log('facts count', Object.keys(facts).length);
  console.log('facts sample', Object.fromEntries(Object.entries(facts).slice(0, 30)));
  console.log('missing count', missingFields.length);
  console.log('missing sample', missingFields.slice(0, 30));
  console.groupEnd();
  await persistLeadContext({
    detail: result.detail,
    leadId: result.leadId,
    facts,
    missingFields,
    dreDocuments: dreResult.dreDocuments,
    dreDocumentError: dreResult.error,
    leadContext,
  });
  pushLeadContextToOffscreen({ leadId: result.leadId, facts, missingFields });
  return {
    leadId: leadContext?.lead_id || result.leadId,
    detail: result.detail,
    facts,
    missingFields,
    dreDocuments: dreResult.dreDocuments,
    dreDocumentError: leadContext?.document_error || dreResult.error,
    leadContext,
    documentStatus: leadContext?.document_status || null,
  };
}

async function loadLeadDetailForChat(message, stored) {
  const requestedLeadId = message.lead_id || message.leadId || stored.currentLeadId || null;
  const storedLeadId = stored.currentLeadId || null;
  const hasRequestedDifferentLead = requestedLeadId && storedLeadId && String(requestedLeadId) !== String(storedLeadId);

  if (!hasRequestedDifferentLead && (message.lead_context || message.leadContext || stored.currentLeadContext)) {
    const leadContext = message.lead_context || message.leadContext || stored.currentLeadContext;
    const detail = message.lead_detail || message.leadDetail || stored.currentLeadDetail || leadContext?.lead_detail || null;
    const facts = message.lead_facts || message.leadFacts || stored.currentLeadFacts || leadContext?.facts || null;
    return {
      leadId: leadContext?.lead_id || requestedLeadId,
      detail,
      facts,
      missingFields: message.lead_missing_fields || message.leadMissingFields || stored.currentLeadMissingFields || null,
      dreDocuments: message.lead_dre_documents || message.leadDreDocuments || stored.currentLeadDreDocuments || null,
      dreDocumentError: message.lead_dre_document_error || message.leadDreDocumentError || stored.currentLeadDreDocumentError || leadContext?.document_error || null,
      documentStatus: message.lead_document_status || message.leadDocumentStatus || stored.currentLeadDocumentStatus || leadContext?.document_status || null,
      leadContext,
    };
  }

  if (!hasRequestedDifferentLead && (message.lead_detail || message.leadDetail || stored.currentLeadDetail)) {
    const detail = message.lead_detail || message.leadDetail || stored.currentLeadDetail || null;
    const facts = LeadDetailApi.buildLeadFacts(detail);
    const missingFields = LeadDetailApi.buildLeadMissingFields(detail);
    const dreDocuments = message.lead_dre_documents || message.leadDreDocuments || stored.currentLeadDreDocuments || null;
    const dreDocumentError = message.lead_dre_document_error || message.leadDreDocumentError || stored.currentLeadDreDocumentError || null;
    const documentStatus = message.lead_document_status || message.leadDocumentStatus || stored.currentLeadDocumentStatus || null;
    const leadContext = await buildBackendLeadContext({
      leadId: requestedLeadId,
      detail,
      dreDocuments,
      dreDocumentError,
      leadDocumentStatus: documentStatus,
      leadFacts: facts,
    });
    await persistLeadContext({ detail, leadId: requestedLeadId, facts, missingFields, dreDocuments, dreDocumentError, leadContext });
    return {
      leadId: leadContext?.lead_id || requestedLeadId,
      detail,
      facts,
      missingFields,
      dreDocuments,
      dreDocumentError: leadContext?.document_error || dreDocumentError,
      documentStatus: leadContext?.document_status || documentStatus,
      leadContext,
    };
  }

  const candidateFacts = message.lead_facts || message.leadFacts || stored.currentLeadFacts || null;
  if (!hasRequestedDifferentLead && hasObjectFields(candidateFacts)) {
    const documentStatus = message.lead_document_status || message.leadDocumentStatus || stored.currentLeadDocumentStatus || null;
    const dreDocuments = message.lead_dre_documents || message.leadDreDocuments || stored.currentLeadDreDocuments || null;
    const dreDocumentError = message.lead_dre_document_error || message.leadDreDocumentError || stored.currentLeadDreDocumentError || null;
    const leadContext = await buildBackendLeadContext({
      leadId: requestedLeadId,
      detail: null,
      dreDocuments,
      dreDocumentError,
      leadDocumentStatus: documentStatus,
      leadFacts: candidateFacts,
    });
    await persistLeadContext({
      detail: null,
      leadId: requestedLeadId,
      facts: candidateFacts,
      missingFields: message.lead_missing_fields || message.leadMissingFields || stored.currentLeadMissingFields || null,
      dreDocuments,
      dreDocumentError,
      leadContext,
    });
    return {
      leadId: leadContext?.lead_id || requestedLeadId,
      detail: null,
      facts: candidateFacts,
      missingFields: message.lead_missing_fields || message.leadMissingFields || stored.currentLeadMissingFields || null,
      dreDocuments,
      dreDocumentError: leadContext?.document_error || dreDocumentError,
      documentStatus: leadContext?.document_status || documentStatus,
      leadContext,
    };
  }

  if (requestedLeadId) {
    return fetchAndStoreLeadDetail(requestedLeadId);
  }

  return {
    leadId: stored.currentLeadId || null,
    detail: stored.currentLeadDetail || null,
    facts: stored.currentLeadFacts || null,
    missingFields: stored.currentLeadMissingFields || null,
    dreDocuments: stored.currentLeadDreDocuments || null,
    dreDocumentError: stored.currentLeadDreDocumentError || null,
    documentStatus: stored.currentLeadDocumentStatus || null,
    leadContext: stored.currentLeadContext || null,
  };
}

function handleChatSend(message, sender, sendResponse) {
  chrome.storage.local.get([
    'currentLeadDetail',
    'currentLeadId',
    'currentLeadFacts',
    'currentLeadMissingFields',
    'currentLeadContext',
    'currentLeadDocumentStatus',
    'currentLeadDreDocuments',
    'currentLeadDreDocumentError',
  ])
    .then(async (stored) => {
      const lead = await loadLeadDetailForChat(message, stored);
      const payload = {
        message: message.message || '',
        history: Array.isArray(message.history) ? message.history : [],
        lead_id: lead.leadId || null,
        lead_detail: lead.detail || null,
        lead_facts: lead.facts || null,
        lead_missing_fields: lead.missingFields || null,
        lead_refreshed: Boolean(message.lead_refreshed || message.leadRefreshed),
        lead_dre_documents: lead.dreDocuments || null,
        lead_dre_document_error: lead.dreDocumentError || null,
        lead_document_status: lead.documentStatus || null,
        lead_context: lead.leadContext || null,
      };

      console.group('[LeadDebug][background] /api/chat payload');
      console.log('lead_id', payload.lead_id);
      console.log('has detail', Boolean(payload.lead_detail));
      console.log('detail keys', payload.lead_detail ? Object.keys(payload.lead_detail).slice(0, 30) : []);
      console.log('facts count', payload.lead_facts ? Object.keys(payload.lead_facts).length : 0);
      console.log('facts sample', payload.lead_facts ? Object.fromEntries(Object.entries(payload.lead_facts).slice(0, 30)) : {});
      console.log('missing count', Array.isArray(payload.lead_missing_fields) ? payload.lead_missing_fields.length : 0);
      console.log('missing sample', Array.isArray(payload.lead_missing_fields) ? payload.lead_missing_fields.slice(0, 30) : []);
      console.log('has lead context', Boolean(payload.lead_context));
      console.log('has DRE documents', Boolean(payload.lead_dre_documents));
      console.log('document status', payload.lead_document_status || null);
      console.groupEnd();

      return fetch(`${CONFIG.BACKEND_HTTP_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
    })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      sendResponse({
        reply: data.reply || '',
        lead_id: data.lead_id || null,
        lead_context_used: Boolean(data.lead_context_used),
        lead_context: data.lead_context || null,
        needs_lead_refresh_confirmation: Boolean(data.needs_lead_refresh_confirmation),
        previous_next_step: data.previous_next_step || null,
        used_cached_next_step: Boolean(data.used_cached_next_step),
      });
    })
    .catch((err) => {
      sendResponse({ error: err.message });
    });
  return true;
}

function handleGetLeadDetail(message, sender, sendResponse) {
  fetchAndStoreLeadDetail(message.leadId || message.lead_id)
    .then((result) => {
      sendResponse({
        success: true,
        leadId: result.leadId,
        detail: result.detail,
        missingFields: result.missingFields,
        leadContext: result.leadContext || null,
        documentStatus: result.documentStatus || null,
        dreDocumentError: result.dreDocumentError || null,
      });
    })
    .catch((err) => {
      sendResponse({ error: err.message });
    });
  return true;
}

function handleSessionReady(message) {
  setCurrentSessionId(message.sessionId || null).then(() => {
    chrome.runtime.sendMessage({
      type: 'SESSION_STATUS_CHANGED',
      sessionId: currentSessionId
    }).catch(() => {});
    chrome.storage.local.get(['currentLeadId', 'currentLeadFacts', 'currentLeadMissingFields']).then((stored) => {
      pushLeadContextToOffscreen({
        leadId: stored.currentLeadId || null,
        facts: stored.currentLeadFacts || null,
        missingFields: stored.currentLeadMissingFields || null,
      });
    }).catch(() => {});
  });
  return false;
}

function handleTranscriptReceived(message) {
  chrome.runtime.sendMessage({
    type: 'TRANSCRIPT_UPDATE',
    transcript: message.transcript,
    isFinal: message.isFinal,
    metadata: message.metadata,
    speaker: message.speaker
  }).catch(() => {});
  return false;
}

function handleUtteranceEnd() {
  chrome.runtime.sendMessage({ type: 'UTTERANCE_END' }).catch(() => {});
  return false;
}

function handleUtteranceCommitted(message) {
  saveMessage({
    type: 'user',
    text: message.text,
    utteranceId: message.utteranceId,
    speaker: message.speaker || null
  });
  chrome.runtime.sendMessage({
    type: 'UTTERANCE_COMMITTED',
    utteranceId: message.utteranceId,
    text: message.text,
    speaker: message.speaker || null
  }).catch(() => {});
  return false;
}

function handleAiResponseChunk(message) {
  chrome.runtime.sendMessage({
    type: 'AI_RESPONSE_CHUNK',
    utteranceId: message.utteranceId,
    text: message.text
  }).catch(() => {});
  return false;
}

function handleAiResponseDone(message) {
  saveMessage({
    type: 'ai',
    text: message.fullText,
    utteranceId: message.utteranceId,
    badgeType: message.badgeType || 'suggestion'
  });
  chrome.runtime.sendMessage({
    type: 'AI_RESPONSE_CHUNK',
    utteranceId: message.utteranceId,
    isDone: true,
    finalText: message.fullText
  }).catch(() => {});
  return false;
}

function handleApiError(message) {
  chrome.runtime.sendMessage({
    type: 'API_ERROR',
    source: message.source,
    message: message.message
  }).catch(() => {});
  return false;
}

const MESSAGE_HANDLERS = {
  GET_STATUS: handleGetStatus,
  TOGGLE_CAPTURE: handleToggleCapture,
  TOGGLE_AGENT_MIC_PAUSE: handleToggleAgentMicPause,
  TOGGLE_CAPTURE_MODE: handleToggleCaptureMode,
  LOAD_MESSAGES: handleLoadMessages,
  CLEAR_MESSAGES: handleClearMessages,
  GENERATE_SUMMARY: handleGenerateSummary,
  SUMMARY_CHAT_SEND: handleSummaryChat,
  CHAT_SEND: handleChatSend,
  GET_LEAD_DETAIL: handleGetLeadDetail,
  // Relay messages from offscreen/content scripts
  SESSION_READY: handleSessionReady,
  TRANSCRIPT_RECEIVED: handleTranscriptReceived,
  UTTERANCE_END: handleUtteranceEnd,
  UTTERANCE_COMMITTED: handleUtteranceCommitted,
  AI_RESPONSE_CHUNK: handleAiResponseChunk,
  AI_RESPONSE_DONE: handleAiResponseDone,
  API_ERROR: handleApiError,
};

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const handler = MESSAGE_HANDLERS[message.type];
  if (handler) {
    return handler(message, sender, sendResponse);
  }
  // Unknown message type — ignore silently.
  return false;
});

async function handleToggleCapture_internal() {
  if (isCapturing) {
    await stopCapture();
  } else {
    await startCapture();
  }
  return isCapturing;
}

async function startCapture() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab) {
      return;
    }

    targetTabId = tab.id;
    await setCurrentSessionId(null);

    await ensureContentScriptInjected(targetTabId);
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId });

    const existingContexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
    if (existingContexts.length === 0) {
      await chrome.offscreen.createDocument({
        url: 'offscreen.html',
        reasons: ['USER_MEDIA'],
        justification: 'Capture tab audio and bridge to backend'
      });
    }

    // Slight delay to allow the offscreen document to initialise its listener
    // before we send the START_CAPTURE message.
    setTimeout(() => {
      chrome.runtime.sendMessage({
        type: 'START_CAPTURE',
        streamId,
        captureMode,
        offscreen: true
      }).catch(() => {});
    }, CONFIG.OFFSCREEN_INIT_DELAY_MS);

    isCapturing = true;
    isAgentMicPaused = false;
    await chrome.storage.local.set({ isCapturing: true, isAgentMicPaused: false });
    chrome.runtime.sendMessage({
      type: 'CAPTURE_STATUS_CHANGED',
      active: true,
      agentMicPaused: false
    }).catch(() => {});
  } catch (err) {
    isCapturing = false;
    isAgentMicPaused = false;
    await setCurrentSessionId(null);
    await chrome.storage.local.set({ isCapturing: false, isAgentMicPaused: false });
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: 'Background',
      message: `Failed to start capture: ${err.message}`
    }).catch(() => {});
    chrome.runtime.sendMessage({
      type: 'CAPTURE_STATUS_CHANGED',
      active: false,
      agentMicPaused: false
    }).catch(() => {});
  }
}

async function stopCapture() {
  try {
    chrome.runtime.sendMessage({ type: 'STOP_CAPTURE', offscreen: true }).catch(() => {});
    const existingContexts = await chrome.runtime.getContexts({ contextTypes: ['OFFSCREEN_DOCUMENT'] });
    if (existingContexts.length > 0) {
      await chrome.offscreen.closeDocument();
    }
  } catch (err) {
    console.warn('[stopCapture] Error during teardown:', err.message);
  } finally {
    isCapturing = false;
    isAgentMicPaused = false;
    targetTabId = null;
    await chrome.storage.local.set({ isCapturing: false, isAgentMicPaused: false });
    chrome.runtime.sendMessage({
      type: 'CAPTURE_STATUS_CHANGED',
      active: false,
      agentMicPaused: false
    }).catch(() => {});
  }
}

async function ensureContentScriptInjected(tabId) {
  try {
    const pingPromise = chrome.tabs.sendMessage(tabId, { type: 'PING' });
    const timeoutPromise = new Promise((_, reject) => setTimeout(() => reject(new Error('Timeout')), 100));
    await Promise.race([pingPromise, timeoutPromise]);
  } catch (err) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.url.startsWith('chrome://') || tab.url.startsWith('about:')) {
      return;
    }

    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content.js']
    });
  }
}
