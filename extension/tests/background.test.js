const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const backgroundPath = path.join(__dirname, '..', 'background.js');

function getActionClickHandlerBody(source) {
  const marker = 'chrome.action.onClicked.addListener(async (tab) => {';
  const start = source.indexOf(marker);
  assert.notEqual(start, -1, 'toolbar click handler should exist');

  const bodyStart = start + marker.length;
  const end = source.indexOf('\n});', bodyStart);
  assert.notEqual(end, -1, 'toolbar click handler should be closed');

  return source.slice(bodyStart, end);
}

test('toolbar click opens the side panel without starting capture', () => {
  const source = fs.readFileSync(backgroundPath, 'utf8');
  const handlerBody = getActionClickHandlerBody(source);

  assert.match(handlerBody, /chrome\.sidePanel\.open/);
  assert.doesNotMatch(handlerBody, /\bstartCapture\s*\(/);
  assert.doesNotMatch(handlerBody, /\bhandleToggleCapture\s*\(/);
});

test('lead fetch logs only masked auth token verification', () => {
  const source = fs.readFileSync(backgroundPath, 'utf8');

  assert.match(source, /maskAuthTokenForLog/);
  assert.match(source, /auth token found/);
  assert.match(source, /auth token preview/);
  assert.doesNotMatch(source, /console\.log\([^;]*,\s*pageContext\?\.token\s*\)/s);
});
