import io
import unittest
from unittest.mock import patch

from rich.console import Console

from cortex._engine.utils.console import ProfessionalConsole


class FakeProgress:
    def __init__(self, *args, **kwargs):
        self.start_calls = 0
        self.stop_calls = 0

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def add_task(self, label, total=None):
        return 1

    def remove_task(self, task_id):
        return None


class TestConsoleTaskSummaryTokens(unittest.TestCase):
    def _build_console_and_buffer(self):
        with patch("cortex._engine.utils.console.Progress", FakeProgress):
            runtime_console = ProfessionalConsole()

        buffer = io.StringIO()
        runtime_console.console = Console(file=buffer, force_terminal=False, color_system=None)
        return runtime_console, buffer

    def test_compact_summary_shows_tokens_and_in_out(self):
        runtime_console, buffer = self._build_console_and_buffer()

        runtime_console.task_summary(
            task_id="task-1",
            duration=1.23,
            tokens={"tokens_used": 12, "input_tokens": 7, "output_tokens": 5},
            status="completed",
            final_message=None,
        )

        output = buffer.getvalue()
        self.assertIn("12 tok", output)
        self.assertIn("in/out 7/5", output)

    def test_verbose_summary_uses_fallback_token_keys_with_split(self):
        runtime_console, buffer = self._build_console_and_buffer()
        runtime_console.verbose = True

        runtime_console.task_summary(
            task_id="task-2",
            duration=2.5,
            tokens={"total_tokens": 30, "prompt_tokens": 20, "completion_tokens": 10},
            status="completed",
            final_message=None,
        )

        output = buffer.getvalue()
        self.assertIn("30 tok", output)
        self.assertIn("in/out 20/10", output)
        self.assertIn("tokens=30", output)
        self.assertIn("in=20", output)
        self.assertIn("out=10", output)


if __name__ == "__main__":
    unittest.main()
