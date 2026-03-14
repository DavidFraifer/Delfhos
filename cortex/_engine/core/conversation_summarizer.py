"""
Conversation Summarizer
Processes chat history to extract actionable tasks for the agent
"""

from ..internal.llm import llm_completion_async
from ..utils.console import console
from typing import List, Dict, Any
import asyncio
import threading


def _run_coro_sync(coro):
    """Run coroutine from sync code, including when already in an event loop."""
    try:
        asyncio.get_running_loop()
        loop_running = True
    except RuntimeError:
        loop_running = False

    if not loop_running:
        return asyncio.run(coro)

    result_container = []
    error_container = []

    def _runner():
        try:
            result_container.append(asyncio.run(coro))
        except Exception as e:
            error_container.append(e)

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()

    if error_container:
        raise error_container[0]
    return result_container[0]


class ConversationSummarizer:
    """
    Summarizes conversation history into actionable tasks
    
    This component bridges the gap between frontend chat interfaces and agent execution.
    It takes a conversation history and extracts:
    - The current user request
    - Relevant context from previous messages
    - A clear, actionable task description
    """
    
    def __init__(self, light_llm: str, agent_id: str = "unknown", logger=None):
        self.light_llm = light_llm
        self.agent_id = agent_id
        self.logger = logger
    
    async def summarize_conversation(self, conversation: List[Dict[str, str]], max_history: int = 10, task_id: str = None) -> str:
        """
        Summarize a conversation into an actionable task
        
        Args:
            conversation: List of message dicts with 'role' and 'content' keys
            max_history: Maximum number of conversation messages to include (most recent)
            task_id: Optional task ID to link token usage
        
        Returns:
            Actionable task string for the agent
        """
        if not conversation:
            return ""
        
        # Use provided task_id or fallback to agent_id for logging
        log_id = task_id or self.agent_id
        
        # Take only the most recent messages
        recent_conversation = conversation[-max_history:] if len(conversation) > max_history else conversation
        
        # If only one message, return it directly
        if len(recent_conversation) == 1 and recent_conversation[0].get('role') == 'user':
            return recent_conversation[0].get('content', '')
        
        # Build conversation context
        conversation_text = self._format_conversation(recent_conversation)
        
        # Create summarization prompt
        prompt = f"""You are processing a conversation between a user and an AI assistant. Your task is to extract the user's current request and create a clear, actionable task description for an AI agent.

CONVERSATION:
{conversation_text}

Your task:
1. Identify what the user is asking for in their LATEST message
2. Include any relevant context from previous messages that's needed to complete the task
3. Create a clear, concise, actionable task description
4. If the user is asking a follow-up question, incorporate context from previous messages

CRITICAL GUIDELINES:
- Focus on the user's LATEST request
- MAINTAIN THE ORIGINAL LANGUAGE of the user's request - do NOT translate it
- Keep it under 200 words
- Be specific and actionable
- Include necessary context (e.g., "the email I mentioned earlier", specific names/dates)
- Don't include pleasantries or conversation history that's not relevant

Output ONLY the task description in the SAME LANGUAGE as the user's request, nothing else."""

        try:
            result, token_info = await llm_completion_async(
                prompt=prompt,
                model=self.light_llm,
                max_tokens=300,
                temperature=0.3
            )
            
            task = result.strip()
            
            # Track tokens for conversation summarization
            if token_info and isinstance(token_info, dict):
                token_info.setdefault("llm_calls", 1)
                if self.logger and task_id:
                    self.logger.add_tokens(task_id, token_info, model=self.light_llm, function_name="summarize_conversation")
            
            console.info(
                "SUMMARIZER",
                f"Converted {len(recent_conversation)} messages into task (tokens: {token_info.get('total_tokens', 0)})",
                agent_id=self.agent_id,
                task_id=task_id
            )
            
            return task
            
        except Exception as e:
            console.error(
                "SUMMARIZER",
                f"Failed to summarize conversation: {str(e)}",
                agent_id=self.agent_id
            )
            # Fallback: return the last user message
            return self._get_last_user_message(recent_conversation)
    
    def _format_conversation(self, conversation: List[Dict[str, str]]) -> str:
        """Format conversation for the summarization prompt"""
        formatted = []
        
        for msg in conversation:
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')
            
            if role == 'user':
                formatted.append(f"USER: {content}")
            elif role == 'assistant':
                formatted.append(f"ASSISTANT: {content}")
            elif role == 'system':
                formatted.append(f"SYSTEM: {content}")
            else:
                formatted.append(f"{role.upper()}: {content}")
        
        return "\n\n".join(formatted)
    
    def _get_last_user_message(self, conversation: List[Dict[str, str]]) -> str:
        """Get the last user message from the conversation (fallback)"""
        for msg in reversed(conversation):
            if msg.get('role') == 'user':
                return msg.get('content', '')
        
        return conversation[-1].get('content', '') if conversation else ''
    
    def summarize_conversation_sync(self, conversation: List[Dict[str, str]], max_history: int = 10) -> str:
        """Synchronous version of summarize_conversation"""
        return _run_coro_sync(self.summarize_conversation(conversation, max_history))


def summarize_conversation(conversation: List[Dict[str, str]], light_llm: str, 
                          agent_id: str = "unknown", max_history: int = 10) -> str:
    """
    Standalone function to summarize a conversation
    
    Args:
        conversation: List of message dicts with 'role' and 'content' keys
        light_llm: LLM model to use for summarization
        agent_id: Agent ID for logging
        max_history: Maximum number of messages to include
    
    Returns:
        Actionable task string
    """
    summarizer = ConversationSummarizer(light_llm, agent_id)
    return _run_coro_sync(summarizer.summarize_conversation(conversation, max_history))
