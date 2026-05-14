import unittest

from app.llm.service import build_extraction_field_specs
from app.llm.service import build_field_extraction_prompt
from app.services.contextual_extraction import normalize_contextual_extracted_fields


class ContextualExtractionTest(unittest.TestCase):
    def test_rejects_invalid_pan_before_merge(self):
        fields = normalize_contextual_extracted_fields(
            {"pancard_no": "GGWWPP401."},
            expected_field="customer_pan",
        )

        self.assertEqual(fields, {})

    def test_strips_pan_punctuation_when_pan_is_valid(self):
        fields = normalize_contextual_extracted_fields(
            {"pancard_no": "abcde1234f."},
            expected_field="customer_pan",
        )

        self.assertEqual(fields, {"customer_pan": "ABCDE1234F"})

    def test_accepts_llm_normalized_iso_dob(self):
        fields = normalize_contextual_extracted_fields(
            {"customer_dob": "2000-07-07"},
            expected_field="customer_dob",
        )

        self.assertEqual(fields, {"customer_dob": "2000-07-07"})

    def test_canonical_customer_fields_are_in_extraction_schema(self):
        specs = build_extraction_field_specs({})

        self.assertIn("customer_dob", specs)
        self.assertIn("customer_pan", specs)

    def test_valid_customer_pan_alias_is_accepted(self):
        fields = normalize_contextual_extracted_fields(
            {"customer_pan": "GGWPA4092F"},
            expected_field="customer_pan",
        )

        self.assertEqual(fields, {"customer_pan": "GGWPA4092F"})

    def test_core_mapping_field_normalizes_without_csv_entry(self):
        fields = normalize_contextual_extracted_fields(
            {"doc_status": "Uploaded"},
            expected_field="doc_status",
        )

        self.assertEqual(fields, {"doc_status": "Uploaded"})

    def test_extraction_prompt_assigns_language_understanding_to_llm(self):
        prompt = build_field_extraction_prompt(
            utterance="छह मई दो हजार",
            conversation_context="Agent: DOB bata dijiye\nCustomer: छह मई दो हजार",
            known_fields={},
            field_prompt="- dob: Date of birth\n- loan_amount: Loan amount",
            agent_last_utterance="DOB bata dijiye",
            expected_field="customer_dob",
        )

        self.assertIn("Active expected field:\ncustomer_dob", prompt)
        self.assertIn("Agent's last question:\nDOB bata dijiye", prompt)
        self.assertIn("छह मई दो हजार", prompt)
        self.assertIn("YYYY-MM-DD", prompt)
        self.assertIn("trust Agent's last question", prompt)
        self.assertIn("Never put a state/province/region name in", prompt)

    def test_city_question_does_not_accept_house_number_guess(self):
        fields = normalize_contextual_extracted_fields(
            {"cra_house_number": "Florida", "cra_city": "Noida"},
            expected_field="customer_city",
        )

        self.assertEqual(fields, {"customer_city": "noida"})

    def test_city_question_accepts_state_without_forcing_it_into_city(self):
        fields = normalize_contextual_extracted_fields(
            {"cra_state": "Madhya Pradesh"},
            expected_field="customer_city",
        )

        self.assertEqual(fields, {"customer_state": "madhya pradesh"})

    def test_later_city_state_correction_updates_even_when_next_action_is_stale(self):
        fields = normalize_contextual_extracted_fields(
            {"cra_city": "Noida", "cra_state": "Uttar Pradesh"},
            expected_field="loan_amount",
        )

        self.assertEqual(
            fields,
            {"customer_city": "noida", "customer_state": "uttar pradesh"},
        )

    def test_accepts_expected_mobile(self):
        fields = normalize_contextual_extracted_fields(
            {"mobile": "80852 34483"},
            expected_field="customer_mobile",
        )

        self.assertEqual(fields, {"customer_mobile": "8085234483"})

    def test_agent_loan_amount_question_extracts_hindi_amount_answer(self):
        fields = normalize_contextual_extracted_fields(
            {"loan_amount": "8000000"},
            expected_field="is_property_identified",
            utterance="असी लाख.",
            agent_utterance="सर आपकी लोन अमाउंट कितनी रहेगी?",
        )

        self.assertEqual(fields, {"loan_amount": "8000000"})

    def test_agent_dob_question_extracts_spoken_hindi_date(self):
        fields = normalize_contextual_extracted_fields(
            {"dob": "2000-05-06"},
            expected_field="customer_city",
            utterance="छह मई दो हजार.",
            agent_utterance="सर DOB बता दीजिए.",
        )

        self.assertEqual(fields, {"customer_dob": "2000-05-06"})

    def test_agent_pan_question_extracts_spoken_hindi_pan(self):
        fields = normalize_contextual_extracted_fields(
            {"pancard_no": "GGWWP4012M"},
            expected_field="customer_city",
            utterance="जीजीडब्लूडब्लू पीपी 4012 एम",
            agent_utterance="सर आपका पेन कार्ड नंबर क्या है?",
        )

        self.assertEqual(fields, {"customer_pan": "GGWWP4012M"})

    def test_suggested_last_name_does_not_turn_random_customer_word_into_name(self):
        fields = normalize_contextual_extracted_fields(
            {"last_name": "sister"},
            expected_field=None,
            utterance="sister",
            agent_utterance="Hello, kya meri baat Aman se ho rahi hai?",
        )

        self.assertEqual(fields, {})

    def test_self_identified_first_name_is_still_allowed_without_agent_prompt(self):
        fields = normalize_contextual_extracted_fields(
            {"first_name": "Aman"},
            expected_field=None,
            utterance="haan main Aman bol raha hoon",
            agent_utterance="Hello, kya meri baat Aman se ho rahi hai?",
        )

        self.assertEqual(fields, {"customer_first_name": "Aman"})


if __name__ == "__main__":
    unittest.main()
