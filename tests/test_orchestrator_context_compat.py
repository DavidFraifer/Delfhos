from cortex._engine.core.orchestrator import Orchestrator
from cortex._engine.utils.logger import CORTEXLogger


def test_orchestrator_exposes_legacy_agent_context_dict():
    orchestrator = Orchestrator(
        light_llm="gemini-3.1-flash-lite-preview",
        heavy_llm="gemini-3.1-flash-lite-preview",
        logger=CORTEXLogger(),
        system_prompt="You are concise.",
    )

    assert isinstance(orchestrator.agent_context, dict)
    assert orchestrator.agent_context.get("system_prompt") == "You are concise."


def test_orchestrator_agent_context_empty_when_no_system_prompt():
    orchestrator = Orchestrator(
        light_llm="gemini-3.1-flash-lite-preview",
        heavy_llm="gemini-3.1-flash-lite-preview",
        logger=CORTEXLogger(),
        system_prompt=None,
    )

    assert orchestrator.agent_context == {}
