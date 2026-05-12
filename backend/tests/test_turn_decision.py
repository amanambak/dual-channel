import time
import unittest

from app.services.session_text import decide_turn_action
from app.services.session_text import looks_like_transcription_instruction_leak
from app.services.session_text import should_capture_final_segment
from app.services.session_transport import should_send_transcript_update
from app.services.openai_realtime_client import (
    AGENT_TRANSCRIPTION_PROMPT,
    OpenAIRealtimeTranscriptionClient,
    _build_turn_detection,
    _noise_reduction_config,
)


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


class AgentTranscriptionTest(unittest.TestCase):
    def test_agent_transcription_uses_literal_channel_prompt(self):
        client = OpenAIRealtimeTranscriptionClient(
            {
                "prompt": "Transcribe Indian home-loan calls accurately.",
                "agentPrompt": "Literal agent transcript only.",
            },
            channel="agent",
        )

        self.assertEqual(client._resolve_transcription_prompt(), "Literal agent transcript only.")

    def test_agent_transcription_does_not_fall_back_to_customer_prompt(self):
        client = OpenAIRealtimeTranscriptionClient(
            {"prompt": "Transcribe Indian home-loan calls accurately."},
            channel="agent",
        )

        self.assertEqual(client._resolve_transcription_prompt(), AGENT_TRANSCRIPTION_PROMPT)

    def test_customer_transcription_keeps_customer_prompt(self):
        client = OpenAIRealtimeTranscriptionClient(
            {"prompt": "Transcribe Indian home-loan calls accurately."},
            channel="customer",
        )

        self.assertEqual(
            client._resolve_transcription_prompt(),
            "Transcribe Indian home-loan calls accurately.",
        )

    def test_noise_reduction_can_be_disabled(self):
        self.assertEqual(_noise_reduction_config({"noise_reduction": "none"}, "agent"), {})
        self.assertEqual(_noise_reduction_config({}, "customer"), {})

    def test_default_vad_keeps_more_prefix_audio(self):
        config = _build_turn_detection({})

        self.assertEqual(config["threshold"], 0.45)
        self.assertEqual(config["prefix_padding_ms"], 800)
        self.assertEqual(config["silence_duration_ms"], 700)

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
