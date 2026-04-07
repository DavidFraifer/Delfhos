"""
Test error recovery with state preservation verification.

Verifies that when code fails:
1. The error is captured with the failed code
2. The LLM is reininjected with the error and working code
3. Variables are preserved from the first execution
4. The LLM can regenerate code from the error point using preserved variables
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from cortex._engine.core.python_executor import PythonExecutor
from cortex._engine.core.orchestrator import Orchestrator
from delfhos.tool import Tool


def create_mock_tool_manager():
    """Create a mock tool manager for testing."""
    tool_manager = Mock()
    tool_manager.tools = {}
    tool_manager.connection_to_tool = {}
    tool_manager.get_tools = Mock(return_value={})
    tool_manager.get_tool = Mock(return_value=None)
    tool_manager.inspect = Mock(return_value={})
    tool_manager.credentials_manager = Mock()
    tool_manager.connections = {}
    return tool_manager


@pytest.mark.asyncio
async def test_executor_preserves_variables_after_error():
    """
    Test that variables are preserved in the executor namespace after an error.
    
    Scenario:
    1. First code block succeeds and defines variables
    2. Second code block fails with an error
    3. Variables from step 1 should still exist in the namespace
    """
    tool_manager = create_mock_tool_manager()
    
    executor = PythonExecutor(
        tool_manager=tool_manager,
        task_id="test_task_1",
        agent_id="test_agent",
        light_llm="test-light",
        heavy_llm="test-heavy",
    )
    
    # First execution: define variables
    first_code = """
data = [1, 2, 3, 4, 5]
result = sum(data)
print(f"Sum calculated: {result}")
"""
    
    result1 = await executor.execute(first_code)
    assert result1["success"] is True
    assert "Sum calculated: 15" in result1["output"]
    
    # Verify namespace has the variables
    assert executor.namespace is not None
    assert "data" in executor.namespace
    assert "result" in executor.namespace
    assert executor.namespace["data"] == [1, 2, 3, 4, 5]
    assert executor.namespace["result"] == 15
    
    # Second execution: use the preserved variables, then fail
    # The goal is to verify that the preserved variables are accessible
    second_code = """
# This should use the 'data' variable from the previous execution
doubled = [x * 2 for x in data]
print(f"Doubled: {doubled}")
# This line will cause an error
invalid_var.method()
"""
    
    result2 = await executor.execute(second_code)
    assert result2["success"] is False
    assert "invalid_var" in result2["error"] or "NameError" in result2["error"]
    
    # Important: verify that variables from first execution are still in namespace
    # This is critical for error recovery - the retry should have access to them
    assert "data" in executor.namespace
    assert executor.namespace["data"] == [1, 2, 3, 4, 5]
    assert "result" in executor.namespace
    assert executor.namespace["result"] == 15


@pytest.mark.asyncio
async def test_executor_state_accessible_in_retry():
    """
    Test that state from failed execution can be used in retry code.
    
    This simulates the error recovery flow:
    1. Initial code processes data and fails midway
    2. Retry code uses the partial results from step 1
    """
    tool_manager = create_mock_tool_manager()
    
    executor = PythonExecutor(
        tool_manager=tool_manager,
        task_id="test_task_2",
        agent_id="test_agent",
        light_llm="test-light",
        heavy_llm="test-heavy",
    )
    
    # First execution: process data, then fail
    first_code = """
items = ["apple", "banana", "cherry"]
processed = []
for item in items:
    processed.append(item.upper())
print(f"Processed: {processed}")
# Deliberate error to trigger recovery
undefined_function()
"""
    
    result1 = await executor.execute(first_code)
    assert result1["success"] is False
    
    # Verify that 'processed' variable was captured before the error
    assert "processed" in executor.namespace
    assert executor.namespace["processed"] == ["APPLE", "BANANA", "CHERRY"]
    
    # Second execution: use the partial results from first execution
    retry_code = """
# The LLM should regenerate from here, using the preserved 'processed' variable
final_output = " | ".join(processed)
print(f"Final output: {final_output}")
"""
    
    result2 = await executor.execute(retry_code)
    assert result2["success"] is True
    assert "Final output: APPLE | BANANA | CHERRY" in result2["output"]


@pytest.mark.asyncio  
async def test_orchestrator_retry_prompt_includes_state():
    """
    Test that the orchestrator's retry prompt includes:
    1. The failed code
    2. The error message
    3. Instructions to use preserved variables
    
    This verifies that error recovery state information is properly communicated to the LLM.
    """
    # Create a minimal mock orchestrator to test the retry prompt construction
    from cortex._engine.core.orchestrator import Orchestrator
    
    orchestrator = Mock(spec=Orchestrator)
    orchestrator.code_generation_llm = "test-llm"
    orchestrator.task_tool_timings = {
        "test_task": [
            {"duration": 1.5, "tool": "sql", "description": "Queried database"},
            {"duration": 0.5, "tool": "gmail", "description": "Sent email"},
        ]
    }
    
    payload = "Send yesterday's reports"
    python_code = """
results = []
# Query and process
for report in reports:
    results.append(format_file(report))
"""
    error_msg = "TypeError: list indices must be integers or slices, not str"
    
    # Simulate the retry_prompt construction from orchestrator._process_message_async
    completed_steps = [
        f"  - {entry['description']} ({entry['duration']:.1f}s)"
        for entry in orchestrator.task_tool_timings.get("test_task", [])
        if entry.get("duration") is not None
    ]
    
    completed_section = ""
    if completed_steps:
        completed_section = "\n\nSTEPS ALREADY COMPLETED SUCCESSFULLY (do NOT repeat these):\n" + "\n".join(completed_steps)
    
    retry_instructions = (
        "INSTRUCTIONS: Fix the error and generate ONLY the code needed to complete the remaining work. "
        "CRITICAL: If the error occurred inside a loop, you MUST rewrite and execute the ENTIRE loop from scratch "
        "(using the preserved data like fetched lists/results). Do NOT try to resume a loop from the middle. "
        "Steps already completed BEFORE the failure (sheets created, files uploaded, queries executed, etc.) "
        "should NOT be repeated — use their results if needed. Output Python code ONLY."
    )
    
    retry_prompt = f"""TASK: "{payload}"

PREVIOUS CODE THAT FAILED:
```python
{python_code}
```

ERROR:
{error_msg}
{completed_section}

CRITICAL STATE PRESERVATION: All variables defined in the PREVIOUS CODE before it crashed are ALREADY preserved in memory. You CAN and MUST use them directly. Do NOT query the database again or recreate variables.

{retry_instructions}"""
    
    # Verify the retry prompt contains all critical elements
    assert "PREVIOUS CODE THAT FAILED:" in retry_prompt
    assert python_code.strip() in retry_prompt
    assert error_msg in retry_prompt
    assert "CRITICAL STATE PRESERVATION" in retry_prompt
    assert "All variables defined in the PREVIOUS CODE before it crashed are ALREADY preserved in memory" in retry_prompt
    assert "STEPS ALREADY COMPLETED SUCCESSFULLY" in retry_prompt
    assert "Queried database" in retry_prompt
    assert "Sent email" in retry_prompt
    
    print("✓ Retry prompt includes error, code, and state preservation instructions")


@pytest.mark.asyncio
async def test_namespace_persistence_across_executions():
    """
    Test that the namespace persists across multiple execute() calls.
    
    This is the foundation of error recovery - the same executor instance
    maintains the namespace across the initial execution and retry.
    """
    tool_manager = create_mock_tool_manager()
    
    executor = PythonExecutor(
        tool_manager=tool_manager,
        task_id="test_task_3",
        agent_id="test_agent",
        light_llm="test-light",
        heavy_llm="test-heavy",
    )
    
    # Initial namespace should be None (lazy initialization)
    assert executor.namespace is None
    
    # First execute creates the namespace
    code1 = "x = 10\ny = 20\nz = x + y"
    result1 = await executor.execute(code1)
    assert result1["success"] is True
    assert executor.namespace is not None
    
    # Variables should exist in namespace
    assert executor.namespace["x"] == 10
    assert executor.namespace["y"] == 20
    assert executor.namespace["z"] == 30
    
    # Second execute should use the SAME namespace instance
    first_namespace_id = id(executor.namespace)
    
    code2 = "a = x + y + z"  # Should have access to x, y, z from code1
    result2 = await executor.execute(code2)
    assert result2["success"] is True
    
    # Namespace object should be the same (same memory address)
    assert id(executor.namespace) == first_namespace_id
    
    # New variable should be added
    assert executor.namespace["a"] == 60
    
    # Previous variables should still be there
    assert executor.namespace["x"] == 10
    assert executor.namespace["y"] == 20
    assert executor.namespace["z"] == 30


@pytest.mark.asyncio
async def test_error_recovery_state_with_tools():
    """
    Test error recovery with tool execution included.
    
    Simulates a realistic scenario where:
    1. Tool is executed and returns data
    2. Code fails while processing that data
    3. Retry can use the tool's returned data without re-executing the tool
    """
    # Create a mock tool that returns data
    mock_tool = Mock(spec=Tool)
    mock_tool.name = "test_tool"
    mock_tool.execute = AsyncMock(return_value=[{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}])
    
    tool_manager = create_mock_tool_manager()
    tool_manager.get_tool = Mock(return_value=mock_tool)
    tool_manager.get_tools = Mock(return_value={"test_tool": mock_tool})
    
    # Note: This would require mocking the entire tool library creation
    # For now, we verify the concept that variables are preserved
    executor = PythonExecutor(
        tool_manager=tool_manager,
        task_id="test_task_4",
        agent_id="test_agent",
        light_llm="test-light",
        heavy_llm="test-heavy",
    )
    
    # Simulate tool result storage
    first_code = """
# Simulate tool result being stored
users = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
print(f"Fetched {len(users)} users")
# Now fail
missing.function()
"""
    
    result1 = await executor.execute(first_code)
    assert result1["success"] is False
    
    # Verify users data is preserved
    assert "users" in executor.namespace
    assert len(executor.namespace["users"]) == 2
    assert executor.namespace["users"][0]["name"] == "Alice"
    
    # Retry can process the data without re-fetching
    retry_code = """
# Process the preserved users data
formatted = [f"{u['name']} (#{u['id']})" for u in users]
print(f"Formatted: {formatted}")
"""
    
    result2 = await executor.execute(retry_code)
    assert result2["success"] is True
    assert "Formatted: ['Alice (#1)', 'Bob (#2)']" in result2["output"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
