// content.js — Minimal script for native Side Panel version

function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch (err) {
    return null;
  }
}

function normalizeStorageToken(value) {
  if (!value) {
    return '';
  }
  const text = String(value).trim().replace(/^"|"$/g, '');
  const bearerMatch = text.match(/Bearer\s+([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/i);
  if (bearerMatch) {
    return bearerMatch[1];
  }
  const jwtMatch = text.match(/([A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)/);
  return jwtMatch ? jwtMatch[1] : '';
}

function readStorageEntries(storage) {
  const entries = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    entries.push([key, storage.getItem(key)]);
  }
  return entries;
}

function findAmbakAuthToken() {
  const entries = [
    ...readStorageEntries(window.localStorage),
    ...readStorageEntries(window.sessionStorage),
  ];

  const preferredEntry = entries.find(([key, value]) => /token|auth|jwt|access/i.test(key) && normalizeStorageToken(value));
  if (preferredEntry) {
    return normalizeStorageToken(preferredEntry[1]);
  }

  const anyTokenEntry = entries.find(([, value]) => normalizeStorageToken(value));
  return anyTokenEntry ? normalizeStorageToken(anyTokenEntry[1]) : '';
}

function normalizeLeadId(value) {
  const match = String(value ?? '').trim().match(/^\d+$/);
  return match ? Number(match[0]) : null;
}

function findLeadIdInObject(value, depth = 0) {
  if (!value || typeof value !== 'object' || depth > 5) {
    return null;
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    if (/^(lead_id|leadId|leadID)$/.test(key)) {
      const leadId = normalizeLeadId(nestedValue);
      if (leadId) {
        return leadId;
      }
    }
  }

  for (const nestedValue of Object.values(value)) {
    const leadId = findLeadIdInObject(nestedValue, depth + 1);
    if (leadId) {
      return leadId;
    }
  }
  return null;
}

function findAmbakLeadId() {
  const urlLeadId = (() => {
    try {
      const url = new URL(window.location.href);
      for (const key of ['lead_id', 'leadId', 'leadID']) {
        const leadId = normalizeLeadId(url.searchParams.get(key));
        if (leadId) {
          return leadId;
        }
      }
      return null;
    } catch (err) {
      return null;
    }
  })();
  if (urlLeadId) {
    return urlLeadId;
  }

  const entries = [
    ...readStorageEntries(window.localStorage),
    ...readStorageEntries(window.sessionStorage),
  ];

  const directEntry = entries.find(([key, value]) => /lead[_-]?id|leadId/i.test(key) && normalizeLeadId(value));
  if (directEntry) {
    return normalizeLeadId(directEntry[1]);
  }

  for (const [, value] of entries) {
    const parsed = safeJsonParse(value);
    const leadId = findLeadIdInObject(parsed);
    if (leadId) {
      return leadId;
    }
  }
  return null;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'PING') {
    sendResponse({ type: 'PONG' });
    return true;
  }
  if (message.type === 'GET_AMBAK_PAGE_CONTEXT') {
    sendResponse({
      token: findAmbakAuthToken(),
      leadId: findAmbakLeadId(),
      url: window.location.href,
    });
    return true;
  }
});

console.log('[AudioAI] Content script loaded');
