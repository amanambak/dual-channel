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
    is_offer_send
    credit_approval_required
    is_partial_login
    is_semi_login
    is_legal_doc
    partner_id
    parent_partner_id
    assign_to
    verifier_id
    is_login_verified
    is_sanction_verified
    reject_reason_id
    rejection_type
    is_disbursal_verified
    can_verify_without_kyc
    is_status_verified_login
    is_status_verified_sanction
    is_status_verified_disbursal
    created_by
    pre_login_bank_id
    loan_type
    loan_sub_type
    loan_sub_type_name
    tranche_type
    fulfillment_type
    followup_date
    followup_type
    kyc_status
    is_pending_doc_share
    followup_status
    is_periskope_allowed
    assign_to
    is_login_confirmation_send
    doc_status
    bucket_id
    status_id
    created_date
    sub_status_id
    last_sub_status_id
    is_qualified
    is_otp_verified
    is_revisit
    docs_collected
    last_updated_date
    updated_date
    credit_pending
    credit_status
    reportingMonthClosedTranches
    hierarchy_details
    lead_breadcrumb {
      name
      status
      offers {
        label
        status
        uploaded_at
        __typename
      }
      docs {
        label
        status
        note
        uploaded_at
        __typename
      }
      __typename
    }
    disbursement_done
    co_applicant {
      coapplicant_dre_executed: dre_executed
      id
      __typename
    }
    customer {
      customer_id
      customer_dre_executed: dre_executed
      recommended_docs {
        id
        lead_id
        doc_id
        parent_doc_id
        is_doc_uploaded
        updated_by_source
        status
        customer_type
        customer_id
        is_recommended
        __typename
      }
      __typename
    }
    lead_details {
      bank {
        id
        dsa_code
        is_gross_code
        banklang {
          bank_name
          __typename
        }
        __typename
      }
      lead_dre_executed: dre_executed
      lead_id
      bank_id
      verifier_id
      login_amount
      remarks
      no_of_emi
      tenure
      loan_amount
      is_property_identified
      usage_type
      occupancy_status
      property_usage
      agreement_type
      property_type
      property_sub_type
      property_agreement_value
      expected_property_value
      property_value
      property_authority_id
      property_dda_registration
      property_dda_group
      login_number
      approval_date
      login_date
      loan_amount
      approved_emi
      approval_date
      approval_number
      approved_amount
      is_calling
      call_status
      calling_tag
      calling_reason_id
      subvension_type_id
      subvention_applicable
      subvention_remarks
      subvension_amount
      expected_registration_date
      is_expected_registration_date
      user_paid_token_amount
      is_ats_bba_executed
      sheet_details
      subvention_info {
        id
        header_id
        amount
        percentage
        lead_id
        __typename
      }
      cross_sell_type_id
      cross_sell_product_amount
      check_oc_cc
      ready_for_registration
      expected_login_date
      expected_approved_date
      expected_disbursed_date
      lod_applied_date
      lod_apply
      offer_share_date
      house_item_value
      approved_roi
      is_offer
      offer_bank
      offer_loan_amount
      offer_roi
      reported_login_date
      reported_sanction_date
      reported_sanction_amount
      reported_login_amount
      __typename
    }
    checklists {
      id
      lead_id
      checklist_id
      sub_status_id
      is_active
      checklist_complete_date
      checklist_sub_status_id
      checklist_query_sub_status_id
      checklist_remark
      checklist_pendency_on
      checklist_followup_date
      checklist_follow_up_with
      checklist_sub_status {
        id
        name
        query_type
        is_final_status
        checklist_id
        __typename
      }
      __typename
    }
    splitpayment {
      id
      lead_id
      loan_type
      product_sub_type
      disbursed_id
      disbursed_date
      disbursed_amount
      disbursed_tenure
      disbursed_date
      is_tranch_verified
      transaction_done
      transaction_mode
      transaction_date
      payout_expected_date
      calc_payout_expected_date
      pdd_expected_date
      transaction_expected_date
      transaction_id
      is_pdd_pendency
      is_txn_pendency
      is_mis_pendency
      is_payin_pendency
      pdd_status
      pdd_remark
      pdd_date
      pay_in_done
      pay_in_confirm_mode
      pay_in_confirm_date
      pay_in_confirm_amount
      is_transaction_verified
      is_pdd_verified
      is_payout_verified
      is_pay_in_verified
      pay_in_confirm_id
      disbursed_roi
      reporting_month
      reporting_year
      reported_date
      reported_disbursed_amount
      ambak_calculation
      subvention_amount
      subvention_remarks
      tranche_payout_eta {
        id
        tranche_id
        eta_date
        status
        created_at
        updated_at
        __typename
      }
      __typename
    }
    deletiontranche {
      id
      tranche_id
      lead_id
      loan_type
      disbursed_id
      disbursed_amount
      disbursed_date
      disbursed_tenure
      is_tranch_verified
      deletion_type
      deletion_reason
      deleted_date
      __typename
    }
    lead_status_history {
      status_id
      sub_status_id
      __typename
    }
    status_info {
      statuslang {
        status_name
        __typename
      }
      __typename
    }
    sub_status_info {
      substatuslang {
        sub_status_name
        __typename
      }
      __typename
    }
    leaddocs {
      id
      lead_id
      doc_id
      parent_doc_id
      doc_status
      customer_type
      customer_id
      ext
      tranche_id
      docmaster {
        __typename
      }
      __typename
    }
    insurance_lead_details {
      id
      ref_id
      insurance_url
      created_date
      last_updated_date
      insurance_type
      selected_premium
      content_sum_insured
      lead_status_id
      insurance_lead_status {
        id
        label
        __typename
      }
      __typename
    }
    whatsAppUnread {
      unread_count
      latest_created_date
      __typename
    }
    leadSourceInfo {
      sourceId
      source
      subSourceId
      subSource
      __typename
    }
    lead_bt_info {
      lead_id
      previous_loan_amount
      previous_existing_emi
      previous_tenure
      previous_loan_date
      previous_roi
      loan_topup_required_amount
      __typename
    }
    __typename
  }
}
`;
  }

  function normalizeBearerToken(token) {
    if (!token) {
      return '';
    }
    return String(token).replace(/^Bearer\s+/i, '').trim();
  }

  function getPrimaryLeadDetail(detail) {
    if (Array.isArray(detail)) {
      return detail.find((item) => item && typeof item === 'object') || null;
    }
    return detail && typeof detail === 'object' ? detail : null;
  }

  function buildLeadDreDocumentQuery() {
    return `mutation getLeadDreDocument($lead_id: Int!, $type: String!, $customer_id: Int, $coapplicant_id: Int) {
  get_lead_dre_document(
    lead_id: $lead_id
    type: $type
    customer_id: $customer_id
    coapplicant_id: $coapplicant_id
  ) {
    untagged_images {
      id
      ldoc_id
      lead_id
      doc_id
      status
      customer_id
      type
      customer_type
      created_date
      updated_date
      parent_doc_id
      child_name
      parent_name
      tranche_id
      ai_tagged_doc_id
      previous_tagged_doc_id
      __typename
    }
    cam_report {
      id
      ldoc_id
      lead_id
      doc_id
      status
      customer_id
      type
      created_date
      updated_date
      parent_doc_id
      child_name
      parent_name
      ai_tagged_doc_id
      previous_tagged_doc_id
      __typename
    }
    legal_report
    documents
    __typename
  }
}`;
  }

  async function postGraphql({ token, body, errorLabel }) {
    const bearerToken = normalizeBearerToken(token);
    if (!bearerToken) {
      throw new Error('Ambak access token was not found in loan-stage localStorage.');
    }

    const response = await fetch(API_URL, {
      method: 'POST',
      headers: {
        accept: 'application/json',
        api_source: 'finex',
        authorization: `Bearer ${bearerToken}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify(body),
    });

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.message || `${errorLabel} failed with HTTP ${response.status}.`);
    }
    if (Array.isArray(payload.errors) && payload.errors.length > 0) {
      throw new Error(payload.errors.map((error) => error.message).filter(Boolean).join('; ') || `${errorLabel} returned errors.`);
    }

    return payload;
  }

  async function fetchLeadDetail({ leadId, token }) {
    const normalizedLeadId = normalizeLeadId(leadId);

    if (!normalizedLeadId) {
      throw new Error('Lead ID is required to fetch lead details.');
    }

    const payload = await postGraphql({
      token,
      errorLabel: 'Lead detail API',
      body: { variables: {}, query: buildLeadDetailQuery(normalizedLeadId) },
    });

    const leadDetail = payload?.data?.get_lead_detail || null;
    if (!leadDetail) {
      throw new Error(`No lead detail found for lead_id ${normalizedLeadId}.`);
    }

    return { leadId: normalizedLeadId, detail: leadDetail };
  }

  async function fetchLeadDreDocuments({ leadId, token, type = 'customer', customerId = null, coapplicantId = null }) {
    const normalizedLeadId = normalizeLeadId(leadId);
    const normalizedCustomerId = normalizeLeadId(customerId);
    const normalizedCoapplicantId = normalizeLeadId(coapplicantId);
    const normalizedType = String(type || '').trim();

    if (!normalizedLeadId) {
      throw new Error('Lead ID is required to fetch DRE documents.');
    }
    if (!normalizedType) {
      throw new Error('DRE document customer type is required.');
    }

    const payload = await postGraphql({
      token,
      errorLabel: 'Lead DRE document API',
      body: {
        operationName: 'getLeadDreDocument',
        variables: {
          lead_id: normalizedLeadId,
          type: normalizedType,
          customer_id: normalizedCustomerId,
          coapplicant_id: normalizedCoapplicantId,
        },
        query: buildLeadDreDocumentQuery(),
      },
    });

    return {
      leadId: normalizedLeadId,
      type: normalizedType,
      customerId: normalizedCustomerId,
      coapplicantId: normalizedCoapplicantId,
      documents: payload?.data?.get_lead_dre_document || null,
    };
  }

  return {
    extractLeadIdFromUrl,
    fetchLeadDreDocuments,
    fetchLeadDetail,
    getPrimaryLeadDetail,
    isLoanDetailUrl,
  };
})();
