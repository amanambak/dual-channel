import time
import unittest

from app.services.session_text import decide_turn_action
from app.services.session_text import looks_like_transcription_instruction_leak
from app.services.session_text import should_capture_final_segment
from app.services.session_transport import asr_message_to_dict
from app.services.session_transport import extract_sarvam_transcript
from app.services.session_transport import normalize_sarvam_message
from app.services.session_transport import should_send_transcript_update
from app.services.sarvam_client import SarvamClient
from app.services.sarvam_client import build_sarvam_params


def test_agent_turn_does_not_trigger_extraction_or_reply():
    decision = decide_turn_action(
        utterance="Sir loan amount kitna chahiye?",
        average_confidence=0.9,
        speaker="1",
        last_llm_invoked_at=0.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is False
    assert decision.run_reply is False
    assert decision.reason == "agent_context_only"


def test_customer_info_runs_extraction_and_reply_inside_old_cooldown_window():
    decision = decide_turn_action(
        utterance="loan amount 25 lakh cibil score 750",
        average_confidence=0.55,
        speaker="0",
        last_llm_invoked_at=time.monotonic(),
        cooldown=3.0,
    )

    assert decision.run_extraction is True
    assert decision.run_reply is True
    assert decision.reason == "customer_extract_and_reply"


def test_customer_info_runs_extraction_and_reply_outside_cooldown():
    decision = decide_turn_action(
        utterance="loan amount 25 lakh cibil score 750",
        average_confidence=0.9,
        speaker="0",
        last_llm_invoked_at=time.monotonic() - 5.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is True
    assert decision.run_reply is True
    assert decision.reason == "customer_extract_and_reply"


def test_filler_turn_still_triggers_raw_customer_processing():
    decision = decide_turn_action(
        utterance="haan",
        average_confidence=0.9,
        speaker="0",
        last_llm_invoked_at=0.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is True
    assert decision.run_reply is True
    assert decision.reason == "customer_extract_and_reply"


def test_customer_greeting_skips_extraction_but_still_gets_reply():
    decision = decide_turn_action(
        utterance="Hello",
        average_confidence=0.75,
        speaker="0",
        last_llm_invoked_at=0.0,
        cooldown=3.0,
    )

    assert decision.run_extraction is False
    assert decision.run_reply is True
    assert decision.reason == "customer_reply_only"


class AgentTranscriptionTest(unittest.TestCase):
    def test_sarvam_defaults_to_saaras_translit(self):
        client = SarvamClient({})

        self.assertEqual(client.model, "saaras:v3")
        self.assertEqual(client.mode, "translit")
        self.assertEqual(client.language_code, "hi-IN")
        self.assertEqual(client.sample_rate, 16000)
        self.assertEqual(client.input_audio_codec, "pcm_s16le")

    def test_sarvam_params_can_override_audio_settings(self):
        client = SarvamClient(
            {
                "model": "saaras:v3",
                "mode": "codemix",
                "languageCode": "en-IN",
                "sampleRate": 8000,
                "inputAudioCodec": "pcm_l16",
                "encoding": "audio/wav",
                "highVadSensitivity": False,
            },
        )

        self.assertEqual(client.mode, "codemix")
        self.assertEqual(client.language_code, "en-IN")
        self.assertEqual(client.sample_rate, 8000)
        self.assertEqual(client.input_audio_codec, "pcm_l16")
        self.assertEqual(client.encoding, "audio/wav")
        self.assertFalse(client.high_vad_sensitivity)
        self.assertFalse(client.flush_signal)
        self.assertEqual(client.flush_interval_seconds, 0)

    def test_sarvam_connection_config_maps_query_and_header(self):
        client = SarvamClient(
            {"language_code": "hi-IN", "input_audio_codec": "pcm_s16le"}
        )
        client.settings.sarvam_api_key = "test-key"

        url, headers = client.connection_config()

        self.assertIn("language-code=hi-IN", url)
        self.assertIn("input_audio_codec=pcm_s16le", url)
        self.assertNotIn("encoding=", url)
        self.assertEqual(headers, {"Api-Subscription-Key": "test-key"})

    def test_build_sarvam_params_prefers_new_payload_name(self):
        params = build_sarvam_params({"sarvamParams": {"mode": "translit"}})

        self.assertEqual(params, {"mode": "translit"})

    def test_sarvam_transcript_event_is_final_text(self):
        transcript, is_final = extract_sarvam_transcript(
            {"type": "data", "data": {"transcript": "mera phone number hai 9840950950"}}
        )

        self.assertEqual(transcript, "mera phone number hai 9840950950")
        self.assertTrue(is_final)

    def test_sarvam_transcript_supports_multiple_response_shapes(self):
        for payload in (
            {"type": "data", "data": {"text": "hello"}},
            {"type": "data", "data": {"translation": "hello translated"}},
            {"transcript": "root transcript"},
            {"text": "root text"},
            {"translation": "root translation"},
        ):
            transcript, is_final = extract_sarvam_transcript(payload)

            self.assertTrue(transcript)
            self.assertTrue(is_final)

    def test_sarvam_message_parser_accepts_model_dump_objects(self):
        class Message:
            def model_dump(self):
                return {"type": "transcript", "text": "haan"}

        self.assertEqual(
            asr_message_to_dict(Message()),
            {"type": "transcript", "text": "haan"},
        )

    def test_empty_sarvam_data_frame_does_not_become_transcript(self):
        message = normalize_sarvam_message(
            {
                "type": "data",
                "data": {
                    "request_id": "req-1",
                    "transcript": "",
                    "language_code": "hi-IN",
                },
            }
        )

        transcript, is_final = extract_sarvam_transcript(message)

        self.assertEqual(transcript, "")
        self.assertFalse(is_final)

    def test_agent_interim_transcript_update_is_forwarded_raw(self):
        self.assertTrue(
            should_send_transcript_update(
                "Am I speaking with Aman?",
                is_final=False,
                speaker="1",
                confidence=None,
            )
        )

    def test_agent_final_transcript_update_accepts_non_empty_text(self):
        self.assertTrue(
            should_send_transcript_update(
                "hello",
                is_final=True,
                speaker="1",
                confidence=0.95,
            )
        )
        self.assertTrue(
            should_send_transcript_update(
                "Am I speaking with Aman?",
                is_final=True,
                speaker="1",
                confidence=0.95,
            )
        )


class TranscriptHygieneTest(unittest.TestCase):
    def test_transcription_prompt_leak_is_not_filtered_from_raw_transcript(self):
        leaked_prompt = (
            "Transcribe Indian home-loan calls accurately. Expect Hindi, English, "
            "and Hinglish. Prefer Roman-script output for Hindi/Hinglish words, "
            "keep loan and banking terms literal, and do not guess words from "
            "brief noise or cross-talk."
        )

        self.assertFalse(looks_like_transcription_instruction_leak(leaked_prompt))
        self.assertTrue(should_capture_final_segment(leaked_prompt, 0.95))

    def test_transcription_prompt_leak_still_triggers_raw_customer_processing(self):
        decision = decide_turn_action(
            utterance=(
                "Transcribe Indian home-loan calls accurately. Expect Hindi, "
                "English, and Hinglish."
            ),
            average_confidence=0.95,
            speaker="0",
            last_llm_invoked_at=0.0,
            cooldown=3.0,
        )

        self.assertTrue(decision.run_extraction)
        self.assertTrue(decision.run_reply)
        self.assertEqual(decision.reason, "customer_extract_and_reply")
