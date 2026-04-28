// background.js — Service Worker (MV3)
// Orchestrates capture state, UI messages, and storage.

importScripts('config.js');

let isCapturing = false;
let targetTabId = null;
let currentSessionId = null;
let captureMode = 'gmeet';

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
    messages.shift();
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
  startCapture();
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
chrome.storage.local.get(['isCapturing', 'currentSessionId', 'captureMode'], (result) => {
  isCapturing = result.isCapturing || false;
  currentSessionId = result.currentSessionId || null;
  captureMode = result.captureMode === 'rtc' ? 'rtc' : 'gmeet';
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ isCapturing: false, messages: [], currentSessionId: null, captureMode: 'gmeet' });
  isCapturing = false;
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
    sendResponse({ active: isCapturing, sessionId, captureMode });
  });
  return true;
}

function handleToggleCapture(message, sender, sendResponse) {
  handleToggleCapture_internal().then((active) => {
    sendResponse({ active, sessionId: currentSessionId, captureMode });
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
      sendResponse({ reply: data.reply || '' });
    })
    .catch((err) => {
      sendResponse({ error: err.message });
    });
  return true;
}

function handleChatSend(message, sender, sendResponse) {
  const payload = {
    message: message.message || '',
    history: Array.isArray(message.history) ? message.history : []
  };

  fetch(`${CONFIG.BACKEND_HTTP_URL}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      sendResponse({ reply: data.reply || '' });
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
  TOGGLE_CAPTURE_MODE: handleToggleCaptureMode,
  LOAD_MESSAGES: handleLoadMessages,
  CLEAR_MESSAGES: handleClearMessages,
  GENERATE_SUMMARY: handleGenerateSummary,
  SUMMARY_CHAT_SEND: handleSummaryChat,
  CHAT_SEND: handleChatSend,
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
    }, 250);

    isCapturing = true;
    await chrome.storage.local.set({ isCapturing: true });
    chrome.runtime.sendMessage({ type: 'CAPTURE_STATUS_CHANGED', active: true }).catch(() => {});
  } catch (err) {
    isCapturing = false;
    await setCurrentSessionId(null);
    await chrome.storage.local.set({ isCapturing: false });
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: 'Background',
      message: `Failed to start capture: ${err.message}`
    }).catch(() => {});
    chrome.runtime.sendMessage({ type: 'CAPTURE_STATUS_CHANGED', active: false }).catch(() => {});
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
    targetTabId = null;
    await chrome.storage.local.set({ isCapturing: false });
    chrome.runtime.sendMessage({ type: 'CAPTURE_STATUS_CHANGED', active: false }).catch(() => {});
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
