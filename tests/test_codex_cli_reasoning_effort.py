import unittest

from adapters.codex_cli_adapter import CodexCliAdapter


class CodexCliReasoningEffortTests(unittest.TestCase):
    def test_build_command_passes_model_and_reasoning_effort(self):
        adapter = CodexCliAdapter(model="gpt-5.5", reasoning_effort="xhigh")

        command = adapter._build_command(
            codex_path="/usr/bin/codex",
            project_root="/tmp/project",
            summary_file="/tmp/summary.md",
            supports_ask_for_approval=True,
            attempted_resume=False,
            resume_conversation_id=None,
        )

        self.assertIn("--model", command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.5")
        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-c") + 1], 'model_reasoning_effort="xhigh"')

    def test_build_command_omits_reasoning_effort_when_unset(self):
        adapter = CodexCliAdapter(model="gpt-5.5")

        command = adapter._build_command(
            codex_path="/usr/bin/codex",
            project_root="/tmp/project",
            summary_file="/tmp/summary.md",
            supports_ask_for_approval=False,
            attempted_resume=False,
            resume_conversation_id=None,
        )

        self.assertIn("--model", command)
        self.assertNotIn("-c", command)
        self.assertFalse(any("model_reasoning_effort" in item for item in command))

    def test_resume_command_passes_reasoning_effort(self):
        adapter = CodexCliAdapter(reasoning_effort="xhigh")

        command = adapter._build_command(
            codex_path="/usr/bin/codex",
            project_root="/tmp/project",
            summary_file="/tmp/summary.md",
            supports_ask_for_approval=True,
            attempted_resume=True,
            resume_conversation_id="session-123",
        )

        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-c") + 1], 'model_reasoning_effort="xhigh"')
        self.assertIn("session-123", command)


if __name__ == "__main__":
    unittest.main()
