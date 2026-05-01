// utils.js — Shared utility functions for Ambak extension

/**
 * Normalizes a lead ID value to a numeric ID or null if invalid.
 * @param {string|number|null|undefined} value
 * @returns {number|null}
 */
function normalizeLeadId(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const match = String(value).trim().match(/^\d+$/);
  return match ? Number(match[0]) : null;
}

/**
 * Normalizes a lead ID from user input (returns string or empty string).
 * @param {string|number|null|undefined} value
 * @returns {string}
 */
function normalizeLeadIdInput(value) {
  const leadId = String(value || '').trim();
  return /^\d+$/.test(leadId) ? leadId : '';
}

/**
 * Normalizes a raw storage token (JWT) to its bare token value.
 * Handles quoted strings, Bearer prefixes, and raw JWTs.
 * @param {string|null|undefined} value
 * @returns {string}
 */
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

/**
 * Normalizes a bearer token string (removes "Bearer " prefix).
 * @param {string|null|undefined} token
 * @returns {string}
 */
function normalizeBearerToken(token) {
  if (!token) {
    return '';
  }
  return String(token).replace(/^Bearer\s+/i, '').trim();
}

/**
 * Safely parse a JSON string, returning null on failure.
 * @param {string} value
 * @returns {object|null}
 */
function safeJsonParse(value) {
  try {
    return JSON.parse(value);
  } catch (err) {
    return null;
  }
}

export {
  normalizeLeadId,
  normalizeLeadIdInput,
  normalizeStorageToken,
  normalizeBearerToken,
  safeJsonParse,
};
