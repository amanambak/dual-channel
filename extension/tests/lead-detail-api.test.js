const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const leadDetailApiPath = path.join(__dirname, '..', 'lead-detail-api.js');

function loadLeadDetailApi(fetchImpl) {
  const sandbox = {
    fetch: fetchImpl,
    self: {},
  };
  vm.runInNewContext(fs.readFileSync(leadDetailApiPath, 'utf8'), sandbox, {
    filename: leadDetailApiPath,
  });
  return sandbox.self.LeadDetailApi;
}

test('fetchLeadDetail posts a lead detail GraphQL query', async () => {
  let requestBody = null;
  const api = loadLeadDetailApi(async (_url, options) => {
    requestBody = JSON.parse(options.body);
    return {
      ok: true,
      json: async () => ({
        data: {
          get_lead_detail: {
            id: 12345,
            lead_details: {
              lead_id: 12345,
            },
          },
        },
      }),
    };
  });

  const result = await api.fetchLeadDetail({ leadId: '12345', token: 'Bearer test-token' });

  assert.equal(result.leadId, 12345);
  assert.equal(result.detail.id, 12345);
  assert.match(requestBody.query, /get_lead_detail\(api_called_by: web, lead_id: 12345\)/);
});
