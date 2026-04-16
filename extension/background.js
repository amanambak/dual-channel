// background.js — Service Worker (MV3)
// Orchestrates capture state, UI messages, and storage.

importScripts('config.js');

let isCapturing = false;
let targetTabId = null;
let currentSessionId = null;

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

chrome.storage.local.get(['isCapturing'], (result) => {
  isCapturing = result.isCapturing || false;
});

chrome.storage.local.get(['currentSessionId'], (result) => {
  currentSessionId = result.currentSessionId || null;
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ isCapturing: false, messages: [], currentSessionId: null });
  isCapturing = false;

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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'GET_STATUS') {
    getCurrentSessionId().then((sessionId) => {
      sendResponse({ active: isCapturing, sessionId });
    });
    return true;
  }

  if (message.type === 'TOGGLE_CAPTURE') {
    handleToggleCapture().then((active) => {
      sendResponse({ active, sessionId: currentSessionId });
    });
    return true;
  }

  if (message.type === 'LOAD_MESSAGES') {
    getMessages().then((messages) => {
      sendResponse({ messages });
    });
    return true;
  }

  if (message.type === 'CLEAR_MESSAGES') {
    clearMessages().then(() => {
      sendResponse({ success: true });
    });
    return true;
  }

  if (message.type === 'GENERATE_SUMMARY') {
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
        : {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ conversation })
          };

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
        const summary = await response.json();
        sendResponse({ summary });
      } catch (err) {
        sendResponse({
          summary: {
            summary: `Failed to generate summary: ${err.message}`
          }
        });
      }
    });
    return true;
  }

  if (message.type === 'SUMMARY_RESULT') {
    sendResponse({ summary: message.summary });
    return true;
  }

  if (message.type === 'API_ERROR') {
    chrome.runtime.sendMessage({
      type: 'API_ERROR',
      source: message.source,
      message: message.message
    }).catch(() => {});
    return false;
  }

  if (message.type === 'SESSION_READY') {
    setCurrentSessionId(message.sessionId || null).then(() => {
      chrome.runtime.sendMessage({
        type: 'SESSION_STATUS_CHANGED',
        sessionId: currentSessionId
      }).catch(() => {});
    });
    return false;
  }

  if (message.type === 'TRANSCRIPT_RECEIVED') {
    chrome.runtime.sendMessage({
      type: 'TRANSCRIPT_UPDATE',
      transcript: message.transcript,
      isFinal: message.isFinal,
      metadata: message.metadata
    }).catch(() => {});
    return false;
  }

  if (message.type === 'UTTERANCE_END') {
    chrome.runtime.sendMessage({ type: 'UTTERANCE_END' }).catch(() => {});
    return false;
  }

  if (message.type === 'UTTERANCE_COMMITTED') {
    saveMessage({
      type: 'user',
      text: message.text,
      utteranceId: message.utteranceId
    });
    return false;
  }

  if (message.type === 'AI_RESPONSE_CHUNK') {
    chrome.runtime.sendMessage({
      type: 'AI_RESPONSE_CHUNK',
      utteranceId: message.utteranceId,
      text: message.text
    }).catch(() => {});
    return false;
  }

  if (message.type === 'AI_RESPONSE_DONE') {
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
});

async function handleToggleCapture() {
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

    setTimeout(() => {
      chrome.runtime.sendMessage({
        type: 'START_CAPTURE',
        streamId,
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
