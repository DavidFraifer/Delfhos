"""
MCP Schema Compiler

Transforms MCP tool schemas into native Delfhos format:
  - ToolCapability + ToolActionSpec for the prefilter registry
  - COMPRESSED_API_DOCS for code generation prompts
  - Python function signatures from JSON Schema inputSchema

Cache system: compiled manifests are saved to ~/.delfhos/mcp_cache/{hash}/
so the MCP server only needs to be introspected once.
"""

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from delfhos.errors import ToolExecutionError


# JSON Schema type → LLM-friendly type annotation (matches build_api_signature output)
_TYPE_MAP = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}

CACHE_DIR = Path.home() / ".delfhos" / "mcp_cache"


class MCPCompiler:
    """
    Compiles MCP tool schemas into Delfhos-native tool_docs and registry entries.
    
    No LLM needed — pure deterministic schema transformation.
    """

    def __init__(self, tool_name: str, command: str, args: List[str] = None, env_keys: List[str] = None):
        """
        Args:
            tool_name: Delfhos tool name (e.g., "github")
            command: Full MCP server command
            args: Additional args (included in cache key)
            env_keys: Env var names (NOT values) for cache key stability
        """
        self.tool_name = tool_name
        self.command = command
        self.args = args or []
        self.env_keys = sorted(env_keys or [])
        self._cache_dir = CACHE_DIR / self._cache_key()
        self.manifest: Optional[Dict[str, Any]] = None

    # ── Public API ────────────────────────────────────────────────────────────

    def compile(self, mcp_tools: List[Dict[str, Any]], server_info: Dict = None) -> Dict[str, Any]:
        """
        Compile a list of MCP tool schemas into Delfhos format.
        
        Args:
            mcp_tools: Raw tools from MCPClient.list_tools()
            server_info: Server info from initialize()
            
        Returns:
            Compiled manifest dict.
        """
        compiled_tools = []
        for tool in mcp_tools:
            compiled_tools.append(self._compile_tool(tool))

        self.manifest = {
            "command": self.command,
            "args": self.args,
            "compiled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "server_name": (server_info or {}).get("name", "unknown"),
            "server_version": (server_info or {}).get("version", "unknown"),
            "tool_name": self.tool_name,
            "tools": compiled_tools,
        }

        self._save_cache()
        return self.manifest

    def load_cache(self) -> Optional[Dict[str, Any]]:
        """Try to load a previously compiled manifest from cache."""
        manifest_path = self._cache_dir / "manifest.json"
        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, "r") as f:
                self.manifest = json.load(f)
            return self.manifest
        except (json.JSONDecodeError, OSError):
            return None

    def get_capability(self):
        """
        Build a ToolCapability from the compiled manifest.
        
        Returns:
            (ToolCapability, action_summaries_dict)
        """
        from ..tools.tool_registry import ToolCapability, ToolActionSpec

        if not self.manifest:
            raise ToolExecutionError(
                tool_name="mcp_compiler",
                detail="No compiled manifest. Call compile() or load_cache() first.",
            )

        actions = []
        summaries = {}

        for tool in self.manifest["tools"]:
            action_name = tool["action_name"]
            actions.append(ToolActionSpec(
                action=action_name,
                description=tool["description"],
                parameters=tool["parameters"],
            ))
            summaries[action_name] = tool["summary"]

        capability = ToolCapability(
            tool_name=self.tool_name,
            actions=actions,
        )
        return capability, summaries

    def get_api_docs(self) -> Dict[str, str]:
        """
        Build COMPRESSED_API_DOCS entries from the compiled manifest.
        
        Returns:
            Dict of "tool:action" → compressed API doc string
        """
        if not self.manifest:
            raise ToolExecutionError(
                tool_name="mcp_compiler",
                detail="No compiled manifest. Call compile() or load_cache() first.",
            )

        docs = {}
        for tool in self.manifest["tools"]:
            key = f"{self.tool_name}:{tool['action_name'].lower()}"
            docs[key] = tool["api_doc"]

        return docs

    def get_tool_names(self) -> List[str]:
        """Get list of MCP tool names from the manifest."""
        if not self.manifest:
            return []
        return [t["mcp_name"] for t in self.manifest["tools"]]

    # ── Single Tool Compilation ───────────────────────────────────────────────

    def _compile_tool(self, tool: Dict[str, Any]) -> Dict[str, Any]:
        """Compile a single MCP tool schema into Delfhos format."""
        mcp_name = tool["name"]
        description = tool.get("description", f"Execute {mcp_name}")
        input_schema = tool.get("inputSchema", {})

        # Build action name: create_issue → CREATE_ISSUE
        action_name = mcp_name.upper().replace("-", "_")

        # Build Python signature and parameters dict
        signature, parameters = self._schema_to_signature(mcp_name, input_schema)

        # Build summary (compact, ~15 tokens for prefilter)
        summary = self._build_summary(description)

        # Build API doc (for code generation prompt)
        api_doc = self._build_api_doc(mcp_name, description, signature, input_schema)

        return {
            "mcp_name": mcp_name,
            "action_name": action_name,
            "description": description,
            "summary": summary,
            "parameters": parameters,
            "python_signature": signature,
            "api_doc": api_doc,
            "input_schema": input_schema,
        }

    def _schema_to_signature(self, func_name: str, schema: Dict[str, Any]) -> Tuple[str, Dict[str, str]]:
        """
        Convert a JSON Schema into a Python function signature.
        
        Args:
            func_name: Function name
            schema: JSON Schema object
            
        Returns:
            (signature_string, parameters_dict)
        """
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        
        parts = []
        parameters = {}

        for prop_name, prop_schema in properties.items():
            type_str = self._describe_json_type(prop_schema)
            prop_desc = prop_schema.get("description", prop_name)
            parameters[prop_name] = prop_desc

            if prop_name in required:
                parts.append(f"{prop_name}: {type_str}")
            else:
                default = self._get_default(prop_schema)
                parts.append(f"{prop_name}: {type_str} = {default}")

        params_str = ", ".join(parts)
        signature = f"{func_name}({params_str})"
        return signature, parameters

    def _describe_json_type(self, prop_schema: Dict[str, Any], _depth: int = 0) -> str:
        """Recursively describe a JSON Schema type, expanding nested objects."""
        return MCPCompiler._describe_json_type_static(prop_schema, _depth)

    @staticmethod
    def _describe_json_type_static(prop_schema: Dict[str, Any], _depth: int = 0) -> str:
        """Recursively describe a JSON Schema type, expanding nested objects."""
        if _depth > 4:
            return "object"

        prop_type = prop_schema.get("type", "string")

        if prop_type == "object":
            nested_props = prop_schema.get("properties", {})
            if nested_props:
                nested_required = set(prop_schema.get("required", []))
                parts = []
                for fname, fprop in nested_props.items():
                    inner = MCPCompiler._describe_json_type_static(fprop, _depth + 1)
                    opt = "" if fname in nested_required else "?"
                    parts.append(f"{fname}{opt}: {inner}")
                return "{" + ", ".join(parts) + "}"
            return "object"

        if prop_type == "array":
            items = prop_schema.get("items", {})
            if items:
                inner = MCPCompiler._describe_json_type_static(items, _depth + 1)
                return f"array[{inner}]"
            return "array"

        return _TYPE_MAP.get(prop_type, prop_type)

    def _get_default(self, prop_schema: Dict[str, Any]) -> str:
        """Get a Python default value from a JSON Schema property."""
        if "default" in prop_schema:
            val = prop_schema["default"]
            if isinstance(val, str):
                return f'"{val}"'
            elif isinstance(val, bool):
                return str(val)
            elif val is None:
                return "None"
            return str(val)
        
        # No explicit default — use None
        return "None"

    def _build_summary(self, description: str) -> str:
        """Build a compact summary for the prefilter (~15 tokens)."""
        # Take first sentence, truncate to ~80 chars
        first_sentence = description.split(".")[0].strip()
        if len(first_sentence) > 80:
            first_sentence = first_sentence[:77] + "..."
        return first_sentence

    def _build_api_doc(self, func_name: str, description: str, signature: str, schema: Dict) -> str:
        """Build the compressed API doc for code generation."""
        lines = [f"# await {self.tool_name}.{signature}",
                 f"# {description}"]

        # Add property descriptions as inline param hints
        props = schema.get("properties", {})
        if props:
            hints = []
            for name, prop in list(props.items())[:6]:  # Max 6 hints
                desc = prop.get("description", "")
                if desc:
                    hints.append(f"#   {name}: {desc}")
            lines.extend(hints)

        return "\n".join(lines)

    # ── Cache Management ──────────────────────────────────────────────────────

    def _cache_key(self) -> str:
        """Generate a stable cache key from command + args + env keys."""
        key_parts = [self.command] + self.args + self.env_keys
        key_str = "|".join(key_parts)
        short_hash = hashlib.sha256(key_str.encode()).hexdigest()[:12]
        # Use tool_name prefix for human-readability
        return f"{self.tool_name}_{short_hash}"

    def _save_cache(self) -> None:
        """Save compiled manifest to disk cache."""
        if not self.manifest:
            return
        
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = self._cache_dir / "manifest.json"
        
        with open(manifest_path, "w") as f:
            json.dump(self.manifest, f, indent=2)

    def clear_cache(self) -> None:
        """Delete the cached manifest for this server."""
        import shutil
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)
