"""
LLM Tool Documentation
=======================

The LLM tool is built-in — it requires no Connection.
It exposes the underlying language model for text analysis, drafting, and extraction.
"""


class LLMDoc:
    """API documentation for the built-in LLM tool."""

    TOOL_NAME = "llm"

    ACTIONS = ["DRAFT", "ANALYZE", "EXTRACT"]

    ACTION_SUMMARIES = {
        "DRAFT":   "Generate text content — emails, reports, messages. Returns ready-to-use text.",
        "ANALYZE": "Analyze, summarize, or process text/data. Returns str.",
        "EXTRACT": "Extract structured JSON from text or images. Returns dict (already parsed).",
    }

    PYTHON_API = {
        "ANALYZE": """\
# llm.analyze() → str
summary = await llm.analyze("Sum: " + str(data), model="heavy", desc="Analyzing")
# model: "heavy" (complex), "light" (formatting). Use string concat for JSON, NO f-strings.
""",

        "EXTRACT": """\
# llm.extract() → dict (parsed)
prompt = "Extract. Return JSON: " + '{"name": "str"}' + ". Text: " + text
data = await llm.extract(prompt, model="light", desc="Extracting")
""",

        "DRAFT": """\
# llm.analyze() also drafts
draft = await llm.analyze("Write email: " + ctx, model="light", desc="Drafting")
""",
    }

    EXAMPLES = {
        "EXTRACT": """\
# Extract structured data from an email body
prompt = "Extract sender's name and deadline. Return JSON: " + '{"name": "str", "deadline": "YYYY-MM-DD"}' + ". Email: " + email["body"]
data = await llm.extract(prompt, model="light", desc="Extracting deadline")
print(data.get("deadline"))
""",
    }
