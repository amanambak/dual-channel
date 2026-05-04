// content.js — Minimal script for native Side Panel version

function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch (err) {
    return null;
  }
}

const LOAN_STAGE_HOST = 'loan-stage.ambak.com';

function isLoanStagePage() {
  return window.location.hostname === LOAN_STAGE_HOST;
}

function normalizeTokenText(value) {
  if (!value) {
    return '';
  }
  const text = String(value).trim().replace(/^"|"$/g, '');
  const bearerMatch = text.match(/^Bearer\s+(.+)$/i);
  if (bearerMatch) {
    return bearerMatch[1].trim();
  }
  return text;
}

function isAccessTokenKey(key) {
  const text = String(key || '');
  return /(^|[._-])access[._-]?token$/i.test(text) && !/refresh/i.test(text);
}

function normalizeAccessToken(value) {
  const token = normalizeTokenText(value);
  const invalidTokenValues = new Set([
    'undefined',
    'null',
    'false',
    'true',
    '[object Object]',
  ]);
  if (!token || /^[{[]/.test(token) || invalidTokenValues.has(token)) {
    return '';
  }
  if (token.length < 20) {
    return '';
  }
  return token;
}

function readStorageEntries(storage) {
  const entries = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    entries.push([key, storage.getItem(key)]);
  }
  return entries;
}

function findAccessTokenInObject(value, depth = 0) {
  if (!value || depth > 6) {
    return '';
  }

  if (typeof value === 'string') {
    const parsed = safeJsonParse(value);
    return parsed ? findAccessTokenInObject(parsed, depth + 1) : '';
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const token = findAccessTokenInObject(item, depth + 1);
      if (token) {
        return token;
      }
    }
    return '';
  }

  if (typeof value !== 'object') {
    return '';
  }

  for (const [key, nestedValue] of Object.entries(value)) {
    if (isAccessTokenKey(key)) {
      const token = normalizeAccessToken(nestedValue);
      if (token) {
        return token;
      }
    }
  }

  for (const nestedValue of Object.values(value)) {
    const token = findAccessTokenInObject(nestedValue, depth + 1);
    if (token) {
      return token;
    }
  }

  return '';
}

function findAmbakAccessToken() {
  if (!isLoanStagePage()) {
    return '';
  }

  const entries = [
    ...readStorageEntries(window.localStorage),
    ...readStorageEntries(window.sessionStorage),
  ];
  for (const [key, value] of entries) {
    if (isAccessTokenKey(key)) {
      const token = normalizeAccessToken(value);
      if (token) {
        return token;
      }
    }
  }

  for (const [, value] of entries) {
    const token = findAccessTokenInObject(safeJsonParse(value));
    if (token) {
      return token;
    }
  }

  return '';
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
    const accessToken = findAmbakAccessToken();
    sendResponse({
      accessToken,
      token: accessToken,
      leadId: findAmbakLeadId(),
      url: window.location.href,
    });
    return true;
  }
});

console.log('[AudioAI] Content script loaded');
