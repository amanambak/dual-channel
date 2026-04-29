// lead-detail-api.js — Ambak lead detail GraphQL helper.

const LeadDetailApi = (() => {
  const API_URL = 'https://api-stage.ambak.com/finex/api/v1';
  const LOAN_DETAIL_HOST = 'loan-stage.ambak.com';
  const LOAN_DETAIL_PATH = '/lead-detail/customer-details/loan-details/';
  const LEAD_ID_KEYS = ['lead_id', 'leadId', 'leadID'];

  function isLoanDetailUrl(rawUrl) {
    try {
      const url = new URL(rawUrl);
      return url.hostname === LOAN_DETAIL_HOST && url.pathname.includes(LOAN_DETAIL_PATH);
    } catch (err) {
      return false;
    }
  }

  function normalizeLeadId(value) {
    if (value === null || value === undefined) {
      return null;
    }
    const match = String(value).trim().match(/^\d+$/);
    return match ? Number(match[0]) : null;
  }

  function extractLeadIdFromUrl(rawUrl) {
    try {
      const url = new URL(rawUrl);
      for (const key of LEAD_ID_KEYS) {
        const searchLeadId = normalizeLeadId(url.searchParams.get(key));
        if (searchLeadId) {
          return searchLeadId;
        }
      }

      const hashQuery = url.hash.includes('?') ? url.hash.slice(url.hash.indexOf('?') + 1) : url.hash.replace(/^#/, '');
      const hashParams = new URLSearchParams(hashQuery);
      for (const key of LEAD_ID_KEYS) {
        const hashLeadId = normalizeLeadId(hashParams.get(key));
        if (hashLeadId) {
          return hashLeadId;
        }
      }

      const numericPathSegment = url.pathname.split('/').map(normalizeLeadId).find(Boolean);
      return numericPathSegment || null;
    } catch (err) {
      return null;
    }
  }

  function buildLeadDetailQuery(leadId) {
    return `{
      get_lead_detail(api_called_by: web, lead_id: ${leadId}) {
        id
        ref_lead_id
        loan_type
        loan_sub_type
        loan_sub_type_name
        status_id
        sub_status_id
        bucket_id
        kyc_status
        followup_date
        followup_type
        followup_status
        partner_name
        partner_mobile
        partner_email
        assign_user {
          id
          name
          email
          mobile
        }
        rmdetails {
          id
          label
          mobile
          email
        }
        status_info {
          statuslang {
            status_name
          }
        }
        sub_status_info {
          substatuslang {
            sub_status_name
          }
        }
        customer {
          customer_id
          first_name
          last_name
          mobile
          email
          pancard_no
          dob
          gender
          marital_status
          occupation
          official_email_id
          employment {
            employer_name
            designation
            gross_monthly_income
            year_with_company
          }
          bank_details {
            bank_id
            branch_name
            account_name
            account_type
          }
        }
        lead_details {
          lead_id
          bank_id
          loan_amount
          login_amount
          approved_amount
          tenure
          annual_income
          monthly_salary
          cibil_score
          company_name
          profession
          property_city
          property_state
          property_address1
          property_address2
          property_pincode
          property_value
          expected_property_value
          bank {
            id
            banklang {
              bank_name
            }
          }
        }
      }
    }`;
  }

  function normalizeBearerToken(token) {
    if (!token) {
      return '';
    }
    return String(token).replace(/^Bearer\s+/i, '').trim();
  }

  async function fetchLeadDetail({ leadId, token }) {
    const normalizedLeadId = normalizeLeadId(leadId);
    const bearerToken = normalizeBearerToken(token);

    if (!normalizedLeadId) {
      throw new Error('Lead ID is required to fetch lead details.');
    }
    if (!bearerToken) {
      throw new Error('Ambak auth token was not found on the lead page.');
    }

    const response = await fetch(API_URL, {
      method: 'POST',
      headers: {
        accept: 'application/json',
        api_source: 'finex',
        authorization: `Bearer ${bearerToken}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify({ variables: {}, query: buildLeadDetailQuery(normalizedLeadId) }),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.message || `Lead detail API failed with HTTP ${response.status}.`);
    }
    if (Array.isArray(payload.errors) && payload.errors.length > 0) {
      throw new Error(payload.errors.map((error) => error.message).filter(Boolean).join('; ') || 'Lead detail API returned errors.');
    }

    const leadDetail = payload?.data?.get_lead_detail || null;
    if (!leadDetail) {
      throw new Error(`No lead detail found for lead_id ${normalizedLeadId}.`);
    }

    return { leadId: normalizedLeadId, detail: leadDetail };
  }

  return {
    extractLeadIdFromUrl,
    fetchLeadDetail,
    isLoanDetailUrl,
  };
})();
