const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const sidepanelJsPath = path.join(__dirname, '..', 'sidepanel.js');
const sidepanelHtmlPath = path.join(__dirname, '..', 'sidepanel.html');

test('sidepanel renders lead refresh confirmation actions', () => {
  const source = fs.readFileSync(sidepanelJsPath, 'utf8');
  const html = fs.readFileSync(sidepanelHtmlPath, 'utf8');

  assert.match(source, /createLeadRefreshActions/);
  assert.match(source, /resolveLeadRefreshActions/);
  assert.match(source, /message\.actions = null/);
  assert.match(source, /Yes, refresh/);
  assert.match(source, /No, same data/);
  assert.match(source, /GET_LEAD_DETAIL/);
  assert.match(source, /lead_refreshed/);
  assert.match(html, /\.chat-actions/);
  assert.match(html, /\.chat-action-btn/);
});

test('sidepanel can collapse call controls behind a bubble', () => {
  const source = fs.readFileSync(sidepanelJsPath, 'utf8');
  const html = fs.readFileSync(sidepanelHtmlPath, 'utf8');

  assert.match(source, /setControlsCollapsed/);
  assert.match(source, /controlsCollapsed/);
  assert.match(source, /controlBubbleBtn\.addEventListener/);
  assert.match(html, /id="control-section"/);
  assert.match(html, /id="controls-toggle-btn"/);
  assert.match(html, /id="control-bubble-btn"/);
  assert.match(html, /\.controls-collapsed \.control-section/);
  assert.match(html, /\.control-bubble/);
});
