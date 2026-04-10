import unittest
from unittest.mock import patch

from cortex._engine.utils.console import ProfessionalConsole


class FakeProgress:
    def __init__(self, *args, **kwargs):
        self.start_calls = 0
        self.stop_calls = 0
        self._next_task_id = 1
        self.tasks = {}

    def start(self):
        self.start_calls += 1

    def stop(self):
        self.stop_calls += 1

    def add_task(self, label, total=None):
        task_id = self._next_task_id
        self._next_task_id += 1
        self.tasks[task_id] = {"label": label, "total": total}
        return task_id

    def remove_task(self, task_id):
        self.tasks.pop(task_id, None)


class TestConsoleLifecycle(unittest.TestCase):
    def _build_console(self):
        with patch("cortex._engine.utils.console.Progress", FakeProgress):
            return ProfessionalConsole()

    def test_nested_suppress_requires_balanced_unsuppress(self):
        console = self._build_console()

        self.assertEqual(console.progress.start_calls, 0)
        console.suppress()
        console.suppress()
        self.assertEqual(console.progress.stop_calls, 0)
        self.assertTrue(console._suppressed)

        console.unsuppress()
        self.assertEqual(console.progress.start_calls, 0)
        self.assertTrue(console._suppressed)

        console.unsuppress()
        self.assertEqual(console.progress.start_calls, 0)
        self.assertFalse(console._suppressed)

    def test_pause_resume_respects_active_suppression(self):
        console = self._build_console()

        console.pause_live()
        self.assertEqual(console.progress.stop_calls, 0)

        console.suppress()
        console.resume_live()

        # Still suppressed, so resuming pause must not restart progress yet.
        self.assertEqual(console.progress.start_calls, 0)

        console.unsuppress()
        self.assertEqual(console.progress.start_calls, 0)

    def test_loading_start_skipped_while_paused(self):
        console = self._build_console()

        console.pause_live(clear_tasks=True)
        console.loading_start("Working", "task-1")
        self.assertNotIn("task-1", console._loading_tasks)

        console.resume_live()
        console.loading_start("Working", "task-1")
        self.assertIn("task-1", console._loading_tasks)
        self.assertEqual(console.progress.start_calls, 1)

        console.loading_stop("task-1")
        self.assertNotIn("task-1", console._loading_tasks)
        self.assertEqual(console.progress.stop_calls, 1)

    def test_paused_live_context_restores_state_after_error(self):
        console = self._build_console()

        console.loading_start("Working", "task-ctx")
        self.assertTrue(console._progress_running)

        with self.assertRaises(RuntimeError):
            with console.paused_live(clear_tasks=True):
                raise RuntimeError("boom")

        self.assertEqual(console._pause_depth, 0)
        self.assertFalse(console._progress_running)


if __name__ == "__main__":
    unittest.main()
