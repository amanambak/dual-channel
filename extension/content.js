// content.js — Minimal script for native Side Panel version

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'PING') {
    sendResponse({ type: 'PONG' });
    return true;
  }
});

console.log('[AudioAI] Content script loaded');
