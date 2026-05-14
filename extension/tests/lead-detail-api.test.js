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
  assert.match(requestBody.query, /assign_user\s*{[\s\S]*name[\s\S]*email/);
  assert.match(requestBody.query, /reportingMonthClosedTranches\s+hierarchy_details\s+lead_breadcrumb/);
  assert.match(requestBody.query, /rmdetails\s*{\s*label\s*mobile\s*email/);
  assert.match(requestBody.query, /co_applicant\s*{[\s\S]*relationship_with_customer[\s\S]*ca_no_of_current_job_years[\s\S]*ca_official_email_id[\s\S]*ca_additional_income\s*{[\s\S]*bank_details\s*{/);
  assert.match(requestBody.query, /customer\s*{[\s\S]*mobile[\s\S]*cra_address1[\s\S]*official_email_id[\s\S]*additional_income\s*{[\s\S]*bank_details\s*{/);
  assert.match(requestBody.query, /lead_details\s*{[\s\S]*annual_income[\s\S]*property_city[\s\S]*cibil_score[\s\S]*reported_login_amount/);
  assert.match(requestBody.query, /whatsAppUnread\s*{\s*mobile\s*unread_count/);
  assert.match(requestBody.query, /utm_params/);
});

test('fetchLeadDetail reports GraphQL validation errors from non-OK responses', async () => {
  const api = loadLeadDetailApi(async () => ({
    ok: false,
    status: 400,
    json: async () => ({
      errors: [{ message: 'Cannot query field "bad_field" on type "LeadDetail".' }],
    }),
  }));

  await assert.rejects(
    () => api.fetchLeadDetail({ leadId: '12345', token: 'test-token' }),
    /Cannot query field "bad_field"/,
  );
});
