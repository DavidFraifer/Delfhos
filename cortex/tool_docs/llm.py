"""
LLM Tool Documentation
=======================

The LLM tool is built-in — it requires no Connection.
It exposes the underlying language model for text analysis, drafting, and extraction.
"""


class LLMDoc:
    """API documentation for the built-in LLM tool."""

    TOOL_NAME = "llm"

    ACTIONS = ["CALL"]

    ACTION_SUMMARIES = {
        "CALL": "Universal method to analyze text/images, generate content or extract structures.",
    }

    PYTHON_API = {
        "CALL": """\
# llm.call() → str (Universal method for ANY task)
# Text task:
summary = await llm.call("Summarize this: " + str(data), desc="Analyzing")

# File analysis (ALWAYS pass inside file_data=[...], prompt must be first positional arg)
vision = await llm.call("Describe this image in detail", file_data=[file_content])

# Structured Extraction:
json_str = await llm.call("Extract. Return strictly JSON: " + '{"name": "str"}')


""",
    }

    EXAMPLES = {
        "CALL": """\
# Extract structured data from a file
prompt = "Extract sender's name and deadline. Return ONLY JSON: " + '{"name": "str", "deadline": "YYYY-MM-DD"}'
data = await llm.call(prompt, file_data=[file_content], desc="Extracting deadline")
""",
    }
