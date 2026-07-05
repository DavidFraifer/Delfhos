"""
Static validator for tool calls in generated code.
==================================================

The codegen LLM occasionally hallucinates tool method names
(``gmail.read``, ``drive.list_files``, ``sheets.write``, ...). Letting that
hallucination reach the runtime costs a full execution attempt: the code
runs, raises ``AttributeError`` mid-flight, then we retry.

This module catches those errors **before execution** by walking the AST
of the generated code, finding every ``<tool>.<method>(...)`` call, and
checking the method actually exists on the corresponding tool library
class. When it does not, we raise ``InvalidToolCall`` with a structured
message that the orchestrator feeds verbatim into the next code-generation
attempt — turning every hallucinated method into a single, self-correcting
round trip instead of a full failed run.

Design choices:
- Only validate **method existence**, not kwargs. Methods often accept
  ``**kwargs`` for tolerance, and trying to validate signatures statically
  would produce false positives on legitimate code.
- Skip dynamic access (``getattr(gmail, ...)``, ``gmail.__class__``, ...).
  These remain runtime-validated and will hit the enriched
  ``__getattr__`` error in :class:`ToolLibraryBase`.
- Underscored names are also skipped (private methods, dunders).

The module is intentionally dependency-free: just stdlib ``ast``.
"""

from __future__ import annotations

import ast
import difflib
import inspect
from typing import Any, Dict, List, Mapping, Optional, Tuple


class InvalidToolCall(Exception):
    """
    Raised when the generated code references a tool method, namespace, or
    parameter that does not exist. The message is structured so it can be shown
    verbatim to the LLM on the next code-generation attempt.

    Each problem dict carries a ``kind``: "method", "namespace", or "param".
    """

    def __init__(self, problems: List[Dict[str, Any]]):
        self.problems = problems
        super().__init__(self._format())

    def _format(self) -> str:
        if not self.problems:
            return "Invalid tool call"
        lines = ["The generated code has invalid tool calls:"]
        for p in self.problems:
            kind = p.get("kind", "method")
            if kind == "namespace":
                lines.append(
                    f'  - `{p["name"]}` is not a tool namespace. '
                    f'Did you mean `{p["suggestion"]}.{p["method"]}(...)`?'
                )
            elif kind == "param":
                for name, suggestion in p["bad_params"]:
                    msg = f'  - `{p["tool"]}.{p["method"]}()` has no parameter `{name}`.'
                    if suggestion:
                        msg += f" Did you mean `{suggestion}=`?"
                    lines.append(msg)
                lines.append(f'    Valid parameters: {", ".join(p["valid_params"])}.')
            else:  # method
                head = f'  - `{p["tool"]}.{p["method"]}(...)` does NOT exist.'
                if p.get("suggestion"):
                    head += f' Did you mean `{p["tool"]}.{p["suggestion"]}(...)`?'
                lines.append(head)
                lines.append(f'    Available methods on `{p["tool"]}`: {", ".join(p["available"])}.')
        lines.append("")
        lines.append(
            "Regenerate using ONLY the methods, namespaces, and parameters listed "
            "above. Do not invent names."
        )
        return "\n".join(lines)


def _public_methods(obj: Any) -> List[str]:
    """Return the sorted list of callable, non-underscore attributes on *obj*."""
    if obj is None:
        return []
    cls = type(obj)
    out: List[str] = []
    seen = set()
    for name in dir(cls):
        if name.startswith("_"):
            continue
        if name in seen:
            continue
        attr = getattr(cls, name, None)
        if attr is None:
            continue
        if callable(attr):
            out.append(name)
            seen.add(name)
    return sorted(out)


def _enumerate_methods(obj: Any) -> Optional[List[str]]:
    """Return the *closed* set of public method names for *obj*, or None when the
    object dispatches methods dynamically and can't be enumerated statically.

    APITool namespaces serve every endpoint (``finnhub.quote``, ...) through
    ``__getattr__`` backed by a private ``_tools`` dict — directly, or behind a
    tracker proxy as ``_original._tools``. ``dir()`` can't see those, so reading
    ``_tools`` is the only way to know the real surface. Other dynamic wrappers
    (custom-tool proxies) have no enumerable surface → return None so the caller
    skips them instead of flagging every call as a hallucination.
    """
    if obj is None:
        return []
    inner = getattr(obj, "_original", obj)          # unwrap tracker proxy if present
    tools = getattr(inner, "_tools", None)
    if isinstance(tools, dict):
        return sorted(tools.keys())                 # API namespace: real endpoints
    if inner is not obj:
        return None                                 # other wrapper: can't enumerate → skip
    return _public_methods(obj)                     # native lib: closed method set


def _suggest(method: str, candidates: List[str]) -> Optional[str]:
    """Return the closest spelling match for *method* among *candidates*, if any."""
    if not candidates:
        return None
    matches = difflib.get_close_matches(method, candidates, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _signature(lib: Any, method_name: str) -> Optional[inspect.Signature]:
    """Introspect the signature of a native library method, or None if it can't
    be introspected (dynamic dispatch, builtins, etc.)."""
    func = getattr(type(lib), method_name, None)
    if func is None or not callable(func):
        return None
    try:
        return inspect.signature(func)
    except (TypeError, ValueError):
        return None


def _valid_param_names(sig: inspect.Signature) -> Optional[List[str]]:
    """Named parameters accepted by *sig* (minus ``self``), or None when the
    method accepts ``**kwargs`` (open signature → don't validate params)."""
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return None
    return [n for n in sig.parameters if n != "self"]


def _param_problem(lib: Any, method_name: str, call: ast.Call) -> Optional[Dict[str, Any]]:
    """Flag keyword arguments in *call* that the method's signature doesn't accept.

    Skips methods with ``**kwargs`` (intentionally tolerant) and any call that
    spreads ``**something`` (we can't know the keys statically).
    """
    sig = _signature(lib, method_name)
    if sig is None:
        return None
    valid = _valid_param_names(sig)
    if valid is None:
        return None
    valid_set = set(valid)
    bad: List[Tuple[str, Optional[str]]] = []
    for kw in call.keywords:
        if kw.arg is None:
            return None  # `**spread` present — can't validate keys statically
        if kw.arg not in valid_set:
            bad.append((kw.arg, _suggest(kw.arg, valid)))
    if not bad:
        return None
    return {"kind": "param", "bad_params": bad, "valid_params": valid}


def _render_signature(lib: Any, method_name: str) -> str:
    """Render one terse, exact signature line, e.g. ``get(spreadsheet_id, range='Sheet1')``.

    Falls back to ``method(...)`` for dynamically dispatched methods that can't
    be introspected (API endpoints).
    """
    sig = _signature(lib, method_name)
    if sig is None:
        return f"{method_name}(...)"
    parts: List[str] = []
    for name, p in sig.parameters.items():
        if name == "self":
            continue
        if p.kind == inspect.Parameter.VAR_KEYWORD:
            parts.append(f"**{name}")
        elif p.kind == inspect.Parameter.VAR_POSITIONAL:
            parts.append(f"*{name}")
        elif p.default is inspect.Parameter.empty:
            parts.append(name)
        else:
            parts.append(f"{name}={p.default!r}")
    return f"{method_name}({', '.join(parts)})"


def render_signature_card(
    libraries: Mapping[str, Any], methods_by_tool: Mapping[str, List[str]]
) -> str:
    """Render exact, token-cheap signatures for the selected tool methods.

    One line per method (``gmail.list(query='', max_results=10)``), introspected
    straight from the live library objects so it can never drift from reality.
    Intended to replace verbose prose docs in the codegen prompt.
    """
    lines: List[str] = []
    for tool in sorted(methods_by_tool):
        lib = libraries.get(tool)
        if lib is None:
            continue
        for method in methods_by_tool[tool]:
            lines.append(f"{tool}.{_render_signature(lib, method)}")
    return "\n".join(lines)


def validate_tool_calls(code: str, libraries: Mapping[str, Any]) -> None:
    """
    Walk the AST of *code* and verify every ``<tool>.<method>(...)`` call
    targets a real method on the corresponding tool library.

    Args:
        code: Source code emitted by the codegen LLM.
        libraries: Mapping ``{name: library_instance}`` of the tool objects
            injected into the execution namespace (e.g. ``{"gmail": <GmailLibrary>}``).

    Raises:
        InvalidToolCall: if any call targets an unknown method. The exception
            carries a structured ``problems`` list and a human-readable message
            suitable for the LLM retry prompt.

    Notes:
        - Returns silently when the code is syntactically invalid; Python's own
          ``SyntaxError`` at execution time gives a clearer message in that case.
        - Flags missing methods, near-miss namespace typos, and unknown keyword
          parameters (only for native methods without ``**kwargs``). Dynamic
          access and dynamically dispatched namespaces are left for runtime.
    """
    if not code or not libraries:
        return
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return  # let the executor surface the syntax error itself

    # Build the method index up front so __getattr__ is only triggered once.
    # Value is None for namespaces that dispatch dynamically (skip validation).
    method_index: Dict[str, Optional[List[str]]] = {
        name: _enumerate_methods(lib) for name, lib in libraries.items()
    }
    known_namespaces = list(method_index.keys())

    problems: List[Dict[str, Any]] = []
    seen: set = set()  # de-duplicate identical problems within one code block

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # Only look at `<name>.<attr>(...)` where <name> is a direct identifier.
        if not isinstance(func, ast.Attribute):
            continue
        if not isinstance(func.value, ast.Name):
            continue
        tool_name = func.value.id
        method_name = func.attr
        if method_name.startswith("_"):
            continue  # private access; let runtime decide

        # ── Unknown namespace: only flag an obvious typo of a real tool ──────
        # (`gmial.send` → gmail). Anything else is assumed a user variable so we
        # never block legitimate `row.get()` / `queue.send()` code. The semantic
        # case (`email.send`) falls through to a retryable runtime NameError.
        if tool_name not in method_index:
            near = difflib.get_close_matches(tool_name, known_namespaces, n=1, cutoff=0.8)
            if near and method_name in (method_index.get(near[0]) or []):
                key = ("ns", tool_name, method_name)
                if key not in seen:
                    seen.add(key)
                    problems.append({
                        "kind": "namespace",
                        "name": tool_name,
                        "method": method_name,
                        "suggestion": near[0],
                    })
            continue

        available = method_index[tool_name]
        if available is None:
            continue  # dynamic-dispatch namespace — can't validate statically

        # ── Unknown method ──────────────────────────────────────────────────
        if method_name not in available:
            key = ("method", tool_name, method_name)
            if key not in seen:
                seen.add(key)
                problems.append({
                    "kind": "method",
                    "tool": tool_name,
                    "method": method_name,
                    "available": available,
                    "suggestion": _suggest(method_name, available),
                })
            continue

        # ── Method exists: validate its keyword parameters ──────────────────
        param_problem = _param_problem(libraries[tool_name], method_name, node)
        if param_problem:
            key = ("param", tool_name, method_name,
                   tuple(name for name, _ in param_problem["bad_params"]))
            if key not in seen:
                seen.add(key)
                param_problem.update({"tool": tool_name, "method": method_name})
                problems.append(param_problem)

    if problems:
        raise InvalidToolCall(problems)


# ─── Tiny self-check ─────────────────────────────────────────────────────────
if __name__ == "__main__":  # pragma: no cover

    class _FakeGmail:
        async def list(self, **kw): ...
        async def send(self, **kw): ...
        async def get_attachments(self, **kw): ...

    libs = {"gmail": _FakeGmail()}

    # 1. Valid code: no error.
    validate_tool_calls("await gmail.list(query='x')\nawait gmail.send(to='a')", libs)

    # 2. Hallucinated method: structured error.
    try:
        validate_tool_calls("await gmail.read(query='x')", libs)
    except InvalidToolCall as e:
        assert e.problems[0]["method"] == "read"
        # Suggestion may be None when no near-match exists; the error is still useful.
        print("OK — hallucination caught:", e.problems[0])

    # 3. Hallucinated near-miss: download_attachments → get_attachments.
    try:
        validate_tool_calls("await gmail.download_attachments(e)", libs)
    except InvalidToolCall as e:
        assert e.problems[0]["suggestion"] == "get_attachments"
        print("OK — near-miss suggested:", e.problems[0])

    # 4. Unknown tool name: ignored (not in libraries).
    validate_tool_calls("await myvar.whatever()", libs)

    # 5. Dynamic access: ignored.
    validate_tool_calls("getattr(gmail, 'read')()", libs)

    # 6. API namespace (endpoints in _tools, invisible to dir): real endpoint OK,
    #    bogus endpoint flagged. This is the Bug-1 regression case.
    class _FakeAPINamespace:
        def __init__(self): self._tools = {"quote": object(), "candles": object()}
        def __getattr__(self, n):  # dynamic dispatch, like the real namespace
            if n in self._tools: return lambda **k: None
            raise AttributeError(n)
    api_libs = {"finnhub": _FakeAPINamespace()}
    validate_tool_calls("await finnhub.quote(symbol='AAPL')", api_libs)  # no error
    try:
        validate_tool_calls("await finnhub.qoute(symbol='AAPL')", api_libs)
    except InvalidToolCall as e:
        assert e.problems[0]["suggestion"] == "quote"
        print("OK — API endpoint typo suggested:", e.problems[0])

    # 7. Dynamic wrapper with no enumerable surface (_original, no _tools): skipped.
    class _FakeCustomProxy:
        def __init__(self): self._original = object()
        def __getattr__(self, n): return lambda *a, **k: None
    validate_tool_calls("await mytool.anything()", {"mytool": _FakeCustomProxy()})  # no error

    # ── New: namespace + param checks (the deterministic alternative to alias hacks) ──

    class _FakeSheets:
        async def get(self, spreadsheet_id, range="Sheet1", desc=None): ...
        async def update(self, spreadsheet_id, data, sheet="Sheet1", cell="A1", desc=None): ...
    sheet_libs = {"sheets": _FakeSheets(), "gmail": _FakeGmail()}

    # 8. Unknown param flagged with the canonical suggestion (the sheets.get bug).
    try:
        validate_tool_calls("await sheets.get(sheet_id='abc', range='A1:Z9')", sheet_libs)
    except InvalidToolCall as e:
        p = e.problems[0]
        assert p["kind"] == "param" and p["bad_params"][0][0] == "sheet_id"
        assert p["bad_params"][0][1] == "spreadsheet_id", p["bad_params"]
        print("OK — bad param caught:", p["bad_params"], "valid:", p["valid_params"])

    # 9. Correct param: no error.
    validate_tool_calls("await sheets.get(spreadsheet_id='abc', range='A1:Z9')", sheet_libs)

    # 10. **kwargs methods are NOT param-validated (gmail.list takes **kw here).
    validate_tool_calls("await gmail.list(anything_goes='ok')", sheet_libs)

    # 11. Namespace typo of a real tool → suggested; user variables left alone.
    try:
        validate_tool_calls("await sheest.get(spreadsheet_id='x')", sheet_libs)
    except InvalidToolCall as e:
        assert e.problems[0]["kind"] == "namespace" and e.problems[0]["suggestion"] == "sheets"
        print("OK — namespace typo suggested:", e.problems[0])
    validate_tool_calls("row.get('k')\nqueue.send(msg)", sheet_libs)  # user vars: no error

    # 12. Signature card: exact, terse, introspected.
    card = render_signature_card(sheet_libs, {"sheets": ["get", "update"]})
    assert "sheets.get(spreadsheet_id, range='Sheet1', desc=None)" in card, card
    print("OK — signature card:\n" + card)

    print("call_validator self-check passed")
