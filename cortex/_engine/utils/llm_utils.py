"""
LLM utility functions for CORTEX Agent
"""

def normalize_llm_result(llm_result):
    """
    Normalize various possible return shapes from llm_completion_async.
    
    Args:
        llm_result: Result from llm_completion_async, can be:
            - tuple: (response, token_info)
            - string: direct response
            - other: converted to string
    
    Returns:
        tuple: (response_string, normalized_token_info_dict)
    """
    response, token_info = "", {}
    
    if isinstance(llm_result, tuple) and len(llm_result) >= 1:
        response = llm_result[0] or ""
        token_info = llm_result[1] if len(llm_result) > 1 and isinstance(llm_result[1], dict) else {}
    else:
        response = llm_result if llm_result is not None else ""
    
    token_info = token_info or {}
    return response, {
        'input_tokens': token_info.get('input_tokens', token_info.get('input', 0)),
        'output_tokens': token_info.get('output_tokens', token_info.get('output', 0)),
        'total_tokens': token_info.get('total_tokens', token_info.get('tokens', 0)),
        'llm_calls': token_info.get('llm_calls', token_info.get('calls', 1))
    }
