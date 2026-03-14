"""
Gmail DSL Parser
Converts natural language user input into strict Gmail DSL commands
"""

from typing import Set, List, Optional, Any
from datetime import datetime, timezone
import asyncio
from ...internal.llm import llm_completion_async


async def parse_gmail_request_async(
    user_input: str,
    permissions: Set[str],
    light_llm: str = None,
    current_date: Optional[str] = None,
    current_time: Optional[str] = None,
    task_id: str = None,
    agent_id: str = None,
    logger: Any = None,
) -> str:
    """
    Async version: Parse natural language Gmail request into DSL format.
    
    Args:
        user_input: Natural language request from user
        permissions: Set of allowed permissions (e.g., {'READ', 'SEND'})
        light_llm: LLM model to use for parsing
    
    Returns:
        DSL command string(s), one per line
    """
    if not light_llm:
        light_llm = "gemini-2.0-flash-lite"
    
    # Build permission string and current date/time
    perm_str = ", ".join(sorted(permissions))
    if not current_date or not current_time:
        current_dt = datetime.now(timezone.utc).astimezone()
        resolved_current_date = current_date or current_dt.strftime("%Y-%m-%d")
        resolved_current_time = current_time or current_dt.strftime("%H:%M %Z")
    else:
        resolved_current_date = current_date
        resolved_current_time = current_time
    
    # System prompt with DSL specification
    system_prompt = """You are a Gmail DSL generator. Convert user requests into strict DSL format.

INPUT:
- user_input (string)
- permissions: subset of {READ, SEND}

OUTPUT:
- ONLY the DSL, no explanation, no markdown, no additional text.
- If multiple actions are needed, output multiple DSL lines (one per line).

DSL FORMAT:
COMMAND{k:v;k:v;...}

COMMANDS:
READ:
  mode: latest | since | range | search
  if latest: max:int (default 5)
  if since: since:YYYY-MM-DD
  if range: from:YYYY-MM-DD;to:YYYY-MM-DD
  if search: q:"keywords"
  optional filters: from:"addr"; to:"addr"; subject:"text"; hasAttachments:true|false; label:"label"; mailbox:"inbox|sent|spam|trash|important|drafts|all"
  include_body:true|false (default false)
  summary:true|false; summary_chars:int
  mark_as_read:true|false (default false)
  var:"descriptive_variable_name" (optional) -> stores metadata of first matching email for later commands

SEND:
  to:[addr,...] (required)
  cc:[...]; bcc:[...]
  subject:"text"
  body:"text"
  format: plain|html (default plain)
  send_at: YYYY-MM-DDThh:mm (optional)
  in_reply_to: message_id (optional)
  draft:true|false (default false)
  confirm:true|false
  var:"descriptive_variable_name" (optional) -> stores send result metadata
  placeholders allowed:
    {{last_read.from}}, {{last_read.subject}}, {{last_read.id}}, {{last_read.body}}
    {{variable_name}} -> value stored via var
    {{variable_name.field}} -> specific field (e.g., from_email, subject, body, id)

DENY:  DENY{reason:"text"}
CLARIFY: CLARIFY{question:"text"}

RULES:
1. If permissions are insufficient → return DENY{reason:"..."}
2. Use multiple lines if user asks for chained actions
3. Use defaults when possible (READ → latest max:5, SEND → draft:true if no recipients)
4. Variable names must be explicit and descriptive (e.g., "last_email_sender", "weekly_report"). Reuse variables with placeholders like {{last_email_sender.from_email}}.
5. Prefer making reasonable assumptions over asking for clarification. Only emit CLARIFY when critical information is missing and no sensible default exists. For subjective requests (e.g. "most important", "interesting"), return the best available data and let the agent decide. Never state that an email was found if you have not issued a READ that can return one.
6. Dates must be ISO-8601.
7. Never output anything except the DSL lines.
8. For READ{mode:search}, always include any keywords the user explicitly supplies exactly as written. Do NOT paraphrase or omit user-provided words or quoted phrases—even if it increases the number of tokens.
9. When composing q:"...", prefer short 1–2 word terms (e.g., separate "monthly report" into `"monthly" "report"`) so the query remains flexible. Add additional short terms only when they meaningfully improve recall. Do NOT embed ISO dates inside q; rely on date filters (`since`, `from`, `to`, or `range`).
10. When the user provides explicit dates (including the year), preserve them exactly. If the user omits the year, assume the current calendar year provided in the context below.
11. When the user asks to find details inside an email (e.g., reservation time, address, confirmation number), issue the READ with `include_body:true` (and `var:"..."` if you need to reference the data). Do NOT emit CLARIFY asking how to proceed—parse the email text yourself after reading it.
12. To inspect messages outside the inbox (e.g., Sent Mail, Drafts), set `mailbox:"sent"` (or another system value such as inbox, spam, trash, drafts, all). This ensures the search targets the correct Gmail system folder.

EXAMPLES:

Input:
user_input: "Show me my last 3 emails"
permissions: {READ}

Output:
READ{mode:latest;max:3;}

---

Input:
user_input: "Find emails from amazon about refund"
permissions: {READ}

Output:
READ{mode:search;q:"amazon refund";max:5;summary:true;summary_chars:300;}

---

Input:
user_input: "Show me the last message I sent to Carlos"
permissions: {READ}

Output:
READ{mode:latest;max:1;mailbox:"sent";to:"carlos@example.com";include_body:true;}

---

Input:
user_input: "Read my latest email and reply thanks"
permissions: {READ,SEND}

Output:
READ{mode:latest;max:1;include_body:true;}
SEND{to:[{{last_read.from}}];subject:"Re: {{last_read.subject}}";body:"Thanks for your email!";format:plain;}

---

Input:
user_input: "Get the last email sender and acknowledge it was received"
permissions: {READ,SEND}

Output:
READ{mode:latest;max:1;include_body:true;var:"last_email_sender";}
SEND{to:[{{last_email_sender.from_email}}];subject:"Re: {{last_email_sender.subject}}";body:"It was received.";format:plain;}

---

Input:
user_input: "Show me the most important recent emails"
permissions: {READ}

Output:
READ{mode:latest;max:5;summary:true;summary_chars:300;}

---

Now convert the following request:"""
    
    # User prompt
    user_prompt = f"""current_date: "{resolved_current_date}"
current_time: "{resolved_current_time}"
user_input: "{user_input}"
permissions: {{{perm_str}}}

Output:"""
    
    try:
        response, token_info = await llm_completion_async(
            model=light_llm,
            prompt=user_prompt,
            system_message=system_prompt,
            temperature=0.0,
            max_tokens=500,
            response_format="text"
        )
        
        # Track tokens for DSL parsing
        if logger and token_info and (task_id or agent_id):
            try:
                token_info.setdefault("llm_calls", 1)
                logger.add_tokens(task_id or agent_id, token_info, light_llm, "gmail_dsl_parsing")
            except Exception:
                pass

        dsl_output = response.strip()
        
        # Clean up any markdown or extra formatting
        if dsl_output.startswith("```"):
            lines = dsl_output.split("\n")
            dsl_output = "\n".join([l for l in lines if not l.startswith("```")])
        
        return dsl_output.strip()
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else str(type(e).__name__)
        print(f"[GMAIL DSL] Async parser exception: {error_msg}")
        return f'DENY{{reason:"Gmail parsing failed - {error_msg}"}}'


def parse_gmail_request(
    user_input: str,
    permissions: Set[str],
    light_llm: str = None,
    current_date: Optional[str] = None,
    current_time: Optional[str] = None,
    task_id: str = None,
    agent_id: str = None,
    logger: Any = None,
) -> str:
    """
    Sync wrapper: Parse natural language Gmail request into DSL format.
    
    Args:
        user_input: Natural language request from user
        permissions: Set of allowed permissions (e.g., {'READ', 'SEND'})
        light_llm: LLM model to use for parsing
    
    Returns:
        DSL command string(s), one per line
    """
    try:
        # Try to use existing event loop if in async context
        try:
            loop = asyncio.get_running_loop()
            # We're inside an event loop - use asyncio.to_thread to run in thread pool
            import threading
            
            # Create a new event loop in a thread
            result_container = []
            error_container = []
            
            def run_async_in_thread():
                try:
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    try:
                        result = new_loop.run_until_complete(
                            parse_gmail_request_async(
                                user_input,
                                permissions,
                                light_llm,
                                current_date=current_date,
                                current_time=current_time,
                                task_id=task_id,
                                agent_id=agent_id,
                                logger=logger,
                            )
                        )
                        result_container.append(result)
                    finally:
                        new_loop.close()
                except Exception as e:
                    error_container.append(e)
            
            thread = threading.Thread(target=run_async_in_thread)
            thread.start()
            thread.join(timeout=20)
            
            if thread.is_alive():
                return 'DENY{reason:"Gmail DSL parsing timed out after 20 seconds"}'
            
            if error_container:
                raise error_container[0]
            
            if result_container:
                return result_container[0]
            
            return 'DENY{reason:"Gmail DSL parsing failed - no result"}'
            
        except RuntimeError:
            # No event loop - just run directly
            return asyncio.run(
                parse_gmail_request_async(
                    user_input,
                    permissions,
                    light_llm,
                    current_date=current_date,
                    current_time=current_time,
                    task_id=task_id,
                    agent_id=agent_id,
                    logger=logger,
                )
            )
        
    except Exception as e:
        error_msg = f"{type(e).__name__}: {str(e)}" if str(e) else str(type(e).__name__)
        print(f"[GMAIL DSL] Sync wrapper exception: {error_msg}")
        return f'DENY{{reason:"Gmail parsing failed - {error_msg}"}}'


def parse_dsl_line(dsl_line: str) -> dict:
    """
    Parse a single DSL line into a structured dictionary.
    
    Args:
        dsl_line: Single DSL command line (e.g., "READ{mode:latest;max:3;}")
    
    Returns:
        Dictionary with 'command' and 'params' keys
    """
    dsl_line = dsl_line.strip()
    
    if not dsl_line or not "{" in dsl_line:
        return {"command": "INVALID", "params": {}}
    
    # Extract command and params safely (support inner braces like {{ }})
    brace_start = dsl_line.find("{")
    brace_end = dsl_line.rfind("}")
    if brace_start == -1 or brace_end == -1 or brace_end <= brace_start:
        return {"command": dsl_line.strip(), "params": {}}

    command = dsl_line[:brace_start].strip()
    params_str = dsl_line[brace_start + 1:brace_end]
    
    # Parse parameters
    params = {}
    if params_str.strip():
        # Split by semicolon, but respect quotes
        in_quotes = False
        current_param = ""
        
        for char in params_str + ";":
            if char == '"':
                in_quotes = not in_quotes
                current_param += char
            elif char == ";" and not in_quotes:
                if current_param.strip():
                    # Parse key:value
                    if ":" in current_param:
                        key, value = current_param.split(":", 1)
                        key = key.strip()
                        value = value.strip()
                        
                        # Remove quotes from values
                        if value.startswith('"') and value.endswith('"'):
                            value = value[1:-1]
                        
                        # Parse arrays [a,b,c]
                        elif value.startswith('[') and value.endswith(']'):
                            inner = value[1:-1]
                            if inner.strip():
                                value = [v.strip() for v in inner.split(',') if v.strip()]
                            else:
                                value = []
                        
                        # Parse booleans (only if not already parsed as array)
                        elif isinstance(value, str) and value.lower() == 'true':
                            value = True
                        elif isinstance(value, str) and value.lower() == 'false':
                            value = False
                        
                        # Parse integers (only if string)
                        else:
                            try:
                                if isinstance(value, str) and '.' not in value:
                                    value = int(value)
                            except (ValueError, TypeError):
                                pass
                        
                        params[key] = value
                current_param = ""
            else:
                current_param += char
    
    return {
        "command": command,
        "params": params
    }

