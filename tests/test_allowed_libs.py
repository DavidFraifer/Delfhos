"""Tests for the allowed_libs feature in Agent and PythonExecutor."""

import asyncio
import unittest
from unittest.mock import MagicMock

from cortex._engine.agent import Agent
from cortex._engine.core.python_executor import PythonExecutor
from cortex._engine.core.sandbox.executor import SandboxExecutor
from cortex._engine.core.sandbox.local import LocalSandbox


class TestAllowedLibsAgent(unittest.TestCase):
    """Verify allowed_libs flows from Agent down to Orchestrator."""

    def test_default_allowed_libs_is_empty(self):
        agent = Agent(tools=[], llm="gemini-3.1-flash-lite")
        self.assertEqual(agent.allowed_libs, [])
        self.assertEqual(agent.orchestrator.allowed_libs, [])

    def test_allowed_libs_stored_on_agent(self):
        agent = Agent(tools=[], llm="gemini-3.1-flash-lite",
                      allowed_libs=["pandas", "numpy"])
        self.assertEqual(agent.allowed_libs, ["pandas", "numpy"])

    def test_allowed_libs_forwarded_to_orchestrator(self):
        agent = Agent(tools=[], llm="gemini-3.1-flash-lite",
                      allowed_libs=["pandas", "requests"])
        self.assertEqual(agent.orchestrator.allowed_libs, ["pandas", "requests"])

    def test_allowed_libs_strips_whitespace(self):
        agent = Agent(tools=[], llm="gemini-3.1-flash-lite",
                      allowed_libs=["  pandas  ", " numpy"])
        self.assertEqual(agent.allowed_libs, ["pandas", "numpy"])

    def test_allowed_libs_filters_empty_strings(self):
        agent = Agent(tools=[], llm="gemini-3.1-flash-lite",
                      allowed_libs=["pandas", "", "  "])
        self.assertEqual(agent.allowed_libs, ["pandas"])


class TestAllowedLibsPythonExecutor(unittest.TestCase):
    """Verify PythonExecutor enforces allowed_libs in _build_namespace."""

    def _make_executor(self, allowed_libs=None):
        mock_manager = MagicMock()
        mock_orchestrator = MagicMock()
        mock_orchestrator.agent_context = {}
        mock_orchestrator.memory = None
        return PythonExecutor(
            tool_manager=mock_manager,
            task_id="test-task",
            agent_id="test-agent",
            light_llm="gemini-3.1-flash-lite",
            heavy_llm="gemini-3.1-flash-lite",
            orchestrator=mock_orchestrator,
            allowed_libs=allowed_libs,
        )

    def test_default_blocks_unlisted_module(self):
        executor = self._make_executor()
        ns = executor._build_namespace({})
        safe_import = ns["__import__"]
        with self.assertRaises(Exception):
            safe_import("pandas")

    def test_allowed_lib_passes_safe_import(self):
        """csv is a stdlib module already in the default whitelist — import must succeed."""
        executor = self._make_executor(allowed_libs=["csv"])
        ns = executor._build_namespace({})
        # csv is always in the default allowed_import_roots, so this should pass
        mod = ns["__import__"]("csv")
        self.assertEqual(mod.__name__, "csv")

    def test_extra_lib_added_to_allowed_roots(self):
        """A user-supplied lib name must appear in the safe-import whitelist."""
        executor = self._make_executor(allowed_libs=["statistics"])
        ns = executor._build_namespace({})
        # statistics is stdlib; it should be importable after being in allowed_libs
        mod = ns["__import__"]("statistics")
        self.assertIsNotNone(mod)

    def test_unlisted_third_party_still_blocked(self):
        """A lib NOT in allowed_libs must still be blocked."""
        executor = self._make_executor(allowed_libs=["csv"])
        ns = executor._build_namespace({})
        with self.assertRaises(Exception):
            ns["__import__"]("os")

    def test_submodule_root_is_checked(self):
        """Importing a submodule (e.g. datetime.timezone) uses the root for the check."""
        executor = self._make_executor()
        ns = executor._build_namespace({})
        # datetime is always allowed
        mod = ns["__import__"]("datetime")
        self.assertIsNotNone(mod)

    def test_allowed_libs_code_execution(self):
        """End-to-end: code that imports an allowed stdlib module executes correctly."""
        executor = self._make_executor(allowed_libs=["statistics"])

        async def run():
            result = await executor.execute(
                "import statistics\nresult = statistics.mean([1, 2, 3, 4, 5])"
            )
            return result

        result = asyncio.run(run())
        self.assertTrue(result.get("success"), result.get("error"))

    def test_blocked_lib_code_execution_fails(self):
        """End-to-end: code that imports a blocked module must fail."""
        executor = self._make_executor()

        async def run():
            return await executor.execute("import os\nresult = os.getcwd()")

        result = asyncio.run(run())
        self.assertFalse(result.get("success"))
        self.assertIn("not allowed", result.get("error", "").lower())


class TestAllowedLibsSandboxExecutor(unittest.TestCase):
    """SandboxExecutor must forward allowed_libs to LocalSandbox."""

    def test_allowed_libs_stored_on_executor(self):
        executor = SandboxExecutor(
            mode="local",
            allowed_libs=["pandas", "numpy"],
            tool_manager=MagicMock(),
            task_id="t1",
            agent_id="a1",
            light_llm="gemini-3.1-flash-lite",
            heavy_llm="gemini-3.1-flash-lite",
        )
        self.assertEqual(executor._allowed_libs, ["pandas", "numpy"])

    def test_local_backend_receives_allowed_libs(self):
        executor = SandboxExecutor(
            mode="local",
            allowed_libs=["statistics"],
            tool_manager=MagicMock(),
            task_id="t1",
            agent_id="a1",
            light_llm="gemini-3.1-flash-lite",
            heavy_llm="gemini-3.1-flash-lite",
        )
        backend = executor._resolve_backend()
        self.assertIsInstance(backend, LocalSandbox)
        self.assertEqual(backend._executor._allowed_libs, ["statistics"])


if __name__ == "__main__":
    unittest.main()
