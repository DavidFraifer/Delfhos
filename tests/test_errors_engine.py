"""
Unit tests for the engine-level Delfhos error classes added in errors.py.
Covers: MemoryRetrievalError, CodeGenerationError, PrefilterError,
        SandboxExecutionError, SQLSchemaError, ConversationCompressionError.
"""
import pytest

from delfhos.errors import (
    CodeGenerationError,
    ConversationCompressionError,
    DelfhosConfigError,
    LLMExecutionError,
    MemoryRetrievalError,
    PrefilterError,
    SQLSchemaError,
    SandboxExecutionError,
    ToolExecutionError,
)


# ── Inheritance ──────────────────────────────────────────────────────────────

class TestInheritance:
    def test_memory_retrieval_error_is_config_error(self):
        assert issubclass(MemoryRetrievalError, DelfhosConfigError)

    def test_code_generation_error_is_llm_error(self):
        assert issubclass(CodeGenerationError, LLMExecutionError)
        assert issubclass(CodeGenerationError, DelfhosConfigError)

    def test_prefilter_error_is_llm_error(self):
        assert issubclass(PrefilterError, LLMExecutionError)

    def test_sandbox_execution_error_is_tool_error(self):
        assert issubclass(SandboxExecutionError, ToolExecutionError)
        assert issubclass(SandboxExecutionError, DelfhosConfigError)

    def test_sql_schema_error_is_tool_error(self):
        assert issubclass(SQLSchemaError, ToolExecutionError)

    def test_conversation_compression_error_is_llm_error(self):
        assert issubclass(ConversationCompressionError, LLMExecutionError)


# ── Error codes are unique and correctly assigned ────────────────────────────

class TestErrorCodes:
    def test_memory_retrieval_code(self):
        assert MemoryRetrievalError.code == "ERR-MEM-002"

    def test_code_generation_code(self):
        assert CodeGenerationError.code == "ERR-LLM-002"

    def test_prefilter_code(self):
        assert PrefilterError.code == "ERR-LLM-003"

    def test_sandbox_execution_code(self):
        assert SandboxExecutionError.code == "ERR-SANDBOX-001"

    def test_sql_schema_code(self):
        assert SQLSchemaError.code == "ERR-TOOL-003"

    def test_conversation_compression_code(self):
        assert ConversationCompressionError.code == "ERR-LLM-004"


# ── Rendered output contains the expected fields ─────────────────────────────

class TestRenderedMessages:
    def test_memory_retrieval_error_renders_detail(self):
        exc = MemoryRetrievalError(detail="embedding model unavailable")
        text = str(exc)
        assert "ERR-MEM-002" in text
        assert "embedding model unavailable" in text
        assert "Hint:" in text

    def test_code_generation_error_renders_detail(self):
        exc = CodeGenerationError(detail="empty response from model")
        text = str(exc)
        assert "ERR-LLM-002" in text
        assert "empty response" in text
        assert "Hint:" in text

    def test_prefilter_error_renders_detail(self):
        exc = PrefilterError(detail="request timed out")
        text = str(exc)
        assert "ERR-LLM-003" in text
        assert "request timed out" in text

    def test_sandbox_execution_error_renders_detail(self):
        exc = SandboxExecutionError(detail="NameError: name 'x' not defined", tool_name="sandbox")
        text = str(exc)
        assert "ERR-SANDBOX-001" in text
        assert "NameError" in text

    def test_sql_schema_error_renders_connection(self):
        exc = SQLSchemaError(connection="sales_db", detail="permission denied")
        text = str(exc)
        assert "ERR-TOOL-003" in text
        assert "sales_db" in text
        assert "permission denied" in text

    def test_conversation_compression_error_renders_detail(self):
        exc = ConversationCompressionError(detail="context window exceeded")
        text = str(exc)
        assert "ERR-LLM-004" in text
        assert "context window exceeded" in text

    def test_manual_message_overrides_template(self):
        exc = SandboxExecutionError(message="Custom sandbox message", tool_name="sandbox", detail="x")
        text = str(exc)
        assert "Custom sandbox message" in text

    def test_missing_kwargs_falls_back_gracefully(self):
        # SQLSchemaError requires 'connection' and 'detail' — omitting both
        exc = SQLSchemaError()
        text = str(exc)
        # Should contain an internal-error notice, not crash
        assert "ERR-" in text

    def test_errors_are_catchable_as_delfhos_config_error(self):
        for cls in (
            MemoryRetrievalError,
            CodeGenerationError,
            PrefilterError,
            SandboxExecutionError,
            SQLSchemaError,
            ConversationCompressionError,
        ):
            try:
                raise cls(detail="test", tool_name="t", connection="c")
            except DelfhosConfigError:
                pass  # correct


# ── Top-level import path ────────────────────────────────────────────────────

class TestTopLevelImport:
    def test_importable_from_delfhos_package(self):
        import delfhos
        for name in (
            "MemoryRetrievalError", "CodeGenerationError", "PrefilterError",
            "SandboxExecutionError", "SQLSchemaError", "ConversationCompressionError",
        ):
            cls = getattr(delfhos, name)
            assert issubclass(cls, DelfhosConfigError)

    def test_in_delfhos_all(self):
        import delfhos
        for name in (
            "MemoryRetrievalError", "CodeGenerationError", "PrefilterError",
            "SandboxExecutionError", "SQLSchemaError", "ConversationCompressionError",
        ):
            assert name in delfhos.__all__
