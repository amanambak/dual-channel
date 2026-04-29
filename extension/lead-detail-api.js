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
    partner_name
    partner_mobile
    partner_email
    partner_contact_name
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
    assign_user {
      id
      name
      email
      mobile
      __typename
    }
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
        uploaded_by_name
        __typename
      }
      docs {
        label
        status
        note
        uploaded_at
        uploaded_by_name
        __typename
      }
      __typename
    }
    rmdetails {
      label
      mobile
      email
      __typename
    }
    disbursement_done
    co_applicant {
      dre_executed
      cibil_pdf
      cibil_status
      id
      ca_mobile
      ca_email
      ca_dob
      ca_type
      same_as_cus_addr
      ca_first_name
      ca_last_name
      ca_gender
      ca_house_type
      ca_mother_name
      ca_father_name
      ca_nationality
      ca_qualification
      ca_pa_city
      ca_pa_house_number
      ca_pa_sameas_cra
      ca_pa_state
      ca_pa_street
      ca_pa_zipcode
      ca_pancard_no
      ca_pan_linked_mobile
      ca_alt_phone
      ca_aadhar_no
      ca_marital_status
      ca_existing_emi
      ca_existing_emi_amount
      ca_annual_income
      ca_profession
      ca_salary_credit_mode
      ca_company_name
      ca_is_itr_filled
      ca_is_form_16_filled
      ca_gross_monthly_salary
      relationship_with_customer
      ca_company_type
      ca_loan_amount
      ca_tenure
      ca_no_of_emi
      ca_property_type
      ca_property_value
      ca_usage_type
      ca_agreement_type
      ca_cra_pincode
      ca_cra_address1
      ca_cra_address2
      ca_cra_city
      ca_cra_state
      ca_office_address
      ca_spouse_name
      ca_designation
      ca_total_work_experience
      ca_no_of_current_job_years
      ca_occupation
      ca_official_email_id
      recommended_docs {
        id
        lead_id
        doc_id
        parent_doc_id
        is_doc_uploaded
        updated_by_source
        status
        doc_upload_url
        customer_type
        customer_id
        is_recommended
        __typename
      }
      ca_monthly_salary
      ca_business_proof
      ca_gross_monthly_salary
      ca_is_additional_income
      ca_no_of_accounts
      ca_offer_type
      ca_emi_ending_six_month
      ca_salutation
      ca_additional_income {
        id
        lead_id
        customer_id
        customer_type
        income_type_id
        amount_type
        amount
        status
        __typename
      }
      ca_is_obligation
      ca_obligation {
        id
        lead_id
        customer_id
        customer_type
        obligation_type_id
        emi_amount
        pending_emi_months
        status
        __typename
      }
      ca_offer_itr_details {
        id
        lead_id
        is_itr_filled
        npat
        depreciation
        interest
        tax_paid
        itr_year
        customer_id
        customer_type
        __typename
      }
      ca_offer_bank_details {
        id
        lead_id
        account_type
        amount
        customer_id
        customer_type
        __typename
      }
      employment_details {
        ca_business_address
        ca_company_phone
        ca_designation
        ca_employer_name
        ca_gross_monthly_income
        ca_industry
        ca_year_with_company
        co_applicant_id
        __typename
      }
      bank_details {
        ca_account_name
        ca_account_number
        ca_account_type
        ca_bank_id
        ca_branch_name
        co_applicant_id
        ca_branch_name
        __typename
      }
      __typename
    }
    customer {
      cibil_pdf
      cibil_status
      customer_id
      mobile
      email
      pancard_no
      pan_link_mobile
      aadhar_no
      first_name
      last_name
      is_dnd
      language_id
      dob
      pa_pincode
      gender
      no_of_dependent
      pa_house_number
      pa_street
      pa_sameas_cra
      cra_house_number
      cra_city
      cra_state
      cra_street
      cra_pincode
      cra_address1
      cra_address2
      house_type
      father_name
      mother_name
      marital_status
      qualification
      duration_of_stay
      dre_executed
      spouse_name
      office_address
      dependents
      designation
      occupation
      official_email_id
      is_comms_disabled
      whatsapp_type
      recommended_docs {
        id
        lead_id
        doc_id
        parent_doc_id
        is_doc_uploaded
        updated_by_source
        status
        doc_upload_url
        customer_type
        customer_id
        is_recommended
        __typename
      }
      no_of_accounts
      business_vintage_years
      business_proof
      industry
      offer_type
      existing_emi_amount
      emi_ending_six_month
      is_additional_income
      salutation
      additional_income {
        id
        lead_id
        customer_id
        customer_type
        income_type_id
        amount_type
        amount
        status
        __typename
      }
      is_obligation
      obligation {
        id
        lead_id
        customer_id
        customer_type
        obligation_type_id
        emi_amount
        pending_emi_months
        status
        __typename
      }
      offer_itr_details {
        id
        lead_id
        is_itr_filled
        npat
        depreciation
        interest
        tax_paid
        itr_year
        customer_id
        customer_type
        __typename
      }
      offer_bank_details {
        id
        lead_id
        account_type
        amount
        customer_id
        customer_type
        __typename
      }
      employment {
        employer_name
        business_address
        company_phone
        designation
        industry
        gross_monthly_income
        year_with_company
        telephone_number
        __typename
      }
      bank_details {
        bank_id
        branch_name
        account_name
        account_type
        account_number
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
      dre_executed
      lead_id
      bank_id
      verifier_id
      login_amount
      remarks
      annual_income
      no_of_emi
      tenure
      loan_amount
      existing_emi
      company_name
      profession
      salary_credit_mode
      existing_emi_amount
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
      preferred_project_name
      property_city
      property_state
      property_address1
      property_address2
      property_pincode
      property_authority_id
      property_other_authority_name
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
      monthly_salary
      cibil_score
      is_calling
      call_status
      calling_tag
      company_type
      company_name
      is_itr_filled
      is_form_16_filled
      gross_monthly_salary
      in_hand_monthly_cash_salary
      company_address
      customer_income_cash_salary_certificate
      customer_earn_cash_income
      time_in_current_co
      In_Account_Turnover_2cr
      itr_file
      work_experience
      calling_reason_id
      subvension_type_id
      subvention_applicable
      subvention_remarks
      subvension_amount
      expected_registration_date
      is_expected_registration_date
      user_paid_token_amount
      is_ats_bba_executed
      customer_contribution
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
      project_name
      builder_name_id
      check_oc_cc
      ready_for_registration
      gross_monthly_salary
      emi_ending_six_month
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
    rmdetails {
      id
      label
      mobile
      __typename
    }
    leaddocs {
      id
      lead_id
      doc_id
      parent_doc_id
      doc_path
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
      mobile
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
      doc_path
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
      doc_path
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

  function buildLeadFacts(detail, maxFields = 2000) {
    const facts = {};

    function visit(value, path = '') {
      if (!value || Object.keys(facts).length >= maxFields) {
        return;
      }
      if (Array.isArray(value)) {
        value.slice(0, 10).forEach((item, index) => visit(item, path ? `${path}[${index}]` : `[${index}]`));
        return;
      }
      if (typeof value === 'object') {
        Object.entries(value).forEach(([key, nestedValue]) => {
          visit(nestedValue, path ? `${path}.${key}` : key);
        });
        return;
      }
      if (value !== null && value !== undefined && value !== '') {
        facts[path] = String(value);
      }
    }

    visit(detail);
    return facts;
  }

  return {
    buildLeadFacts,
    extractLeadIdFromUrl,
    fetchLeadDreDocuments,
    fetchLeadDetail,
    getPrimaryLeadDetail,
    isLoanDetailUrl,
  };
})();
