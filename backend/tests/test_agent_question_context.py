import unittest

from app.models.session import SessionState
from app.services.agent_question_context import current_spoken_expected_field
from app.services.agent_question_context import stamp_next_action


class AgentQuestionContextTest(unittest.TestCase):
    def test_suggestion_is_not_expected_field_until_agent_speaks_after_it(self):
        state = SessionState(session_id="test")
        state.agent_last_utterance = "Hello, kya meri baat Aman se ho rahi hai?"
        state.agent_history.append(state.agent_last_utterance)
        state.last_next_action = stamp_next_action(
            {
                "type": "ask_field",
                "field": "customer_last_name",
                "label": "Customer Last Name",
                "question": "Sir Last Name confirm kar dijiye.",
            },
            state,
        )

        self.assertIsNone(current_spoken_expected_field(state))

    def test_expected_field_becomes_active_when_agent_asks_suggested_field(self):
        state = SessionState(session_id="test")
        state.last_next_action = stamp_next_action(
            {
                "type": "ask_field",
                "field": "customer_last_name",
                "label": "Customer Last Name",
                "question": "Sir Last Name confirm kar dijiye.",
            },
            state,
        )
        state.agent_last_utterance = "last name kya hai?"
        state.agent_history.append(state.agent_last_utterance)

        self.assertEqual(
            current_spoken_expected_field(state),
            "customer_last_name",
        )

    def test_unrelated_agent_question_does_not_activate_suggested_field(self):
        state = SessionState(session_id="test")
        state.last_next_action = stamp_next_action(
            {
                "type": "ask_field",
                "field": "customer_last_name",
                "label": "Customer Last Name",
                "question": "Sir Last Name confirm kar dijiye.",
            },
            state,
        )
        state.agent_last_utterance = "kya abhi baat karne ka sahi time hai?"
        state.agent_history.append(state.agent_last_utterance)

        self.assertIsNone(current_spoken_expected_field(state))


if __name__ == "__main__":
    unittest.main()
