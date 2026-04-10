"""
Tests for OpenAPICompiler and APITool.

Uses a minimal PetStore-style OpenAPI 3.x spec defined inline
so tests run without network access or external files.
"""

import json
import os
import shutil
import tempfile
import pytest
from pathlib import Path

from cortex._engine.api.compiler import OpenAPICompiler, _load_spec, _resolve_ref, _deep_resolve


# ---------------------------------------------------------------------------
# Fixtures: minimal OpenAPI specs
# ---------------------------------------------------------------------------

PETSTORE_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Petstore", "version": "1.0.0"},
    "servers": [{"url": "https://petstore.example.com/v1"}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List all pets",
                "parameters": [
                    {
                        "name": "limit",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "integer", "default": 20},
                        "description": "Maximum number of pets to return",
                    },
                    {
                        "name": "status",
                        "in": "query",
                        "required": False,
                        "schema": {"type": "string", "enum": ["available", "pending", "sold"]},
                        "description": "Filter by status",
                    },
                ],
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["name"],
                                "properties": {
                                    "name": {"type": "string", "description": "Pet name"},
                                    "tag": {"type": "string", "description": "Optional tag"},
                                },
                            }
                        }
                    },
                },
            },
        },
        "/pets/{petId}": {
            "get": {
                "operationId": "showPetById",
                "summary": "Info for a specific pet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "The id of the pet to retrieve",
                    }
                ],
            },
            "delete": {
                "summary": "Delete a pet",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
        },
    },
}

SPEC_WITH_REFS = {
    "openapi": "3.0.3",
    "info": {"title": "RefTest", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/items": {
            "post": {
                "operationId": "createItem",
                "summary": "Create an item",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Item"}
                        }
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "Item": {
                "type": "object",
                "required": ["title"],
                "properties": {
                    "title": {"type": "string", "description": "Item title"},
                    "price": {"type": "number", "description": "Item price"},
                },
            }
        }
    },
}


# ---------------------------------------------------------------------------
# OpenAPICompiler tests
# ---------------------------------------------------------------------------

class TestOpenAPICompiler:

    def test_compile_petstore(self):
        compiler = OpenAPICompiler("petstore", "inline", base_url="https://petstore.example.com/v1")
        manifest = compiler.compile(spec=PETSTORE_SPEC)

        assert manifest["tool_name"] == "petstore"
        assert manifest["api_title"] == "Petstore"
        assert manifest["base_url"] == "https://petstore.example.com/v1"

        tool_names = [t["func_name"] for t in manifest["tools"]]
        assert "list_pets" in tool_names
        assert "create_pet" in tool_names
        assert "show_pet_by_id" in tool_names

    def test_operation_count(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        # 4 operations: GET /pets, POST /pets, GET /pets/{petId}, DELETE /pets/{petId}
        assert len(manifest["tools"]) == 4

    def test_path_params_detected(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        show_pet = next(t for t in manifest["tools"] if t["func_name"] == "show_pet_by_id")

        assert "petId" in show_pet["parameters"]
        path_params = [p for p in show_pet["params_spec"] if p["in"] == "path"]
        assert len(path_params) == 1
        assert path_params[0]["name"] == "petId"
        assert path_params[0]["required"] is True

    def test_query_params_detected(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        list_pets = next(t for t in manifest["tools"] if t["func_name"] == "list_pets")

        assert "limit" in list_pets["parameters"]
        query_params = [p for p in list_pets["params_spec"] if p["in"] == "query"]
        assert len(query_params) == 2
        limit = next(p for p in query_params if p["name"] == "limit")
        assert limit["required"] is False
        assert limit["default"] == 20

    def test_body_params_detected(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        create_pet = next(t for t in manifest["tools"] if t["func_name"] == "create_pet")

        body_params = [p for p in create_pet["params_spec"] if p["in"] == "body"]
        assert len(body_params) == 2
        name_param = next(p for p in body_params if p["name"] == "name")
        assert name_param["required"] is True

    def test_ref_resolution(self):
        compiler = OpenAPICompiler("reftest", "inline")
        manifest = compiler.compile(spec=SPEC_WITH_REFS)
        create_item = manifest["tools"][0]
        body_params = [p for p in create_item["params_spec"] if p["in"] == "body"]
        param_names = [p["name"] for p in body_params]
        assert "title" in param_names
        assert "price" in param_names

    def test_enum_type_description(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        list_pets = next(t for t in manifest["tools"] if t["func_name"] == "list_pets")
        status_param = next(p for p in list_pets["params_spec"] if p["name"] == "status")
        assert "available" in status_param["type"]
        assert "pending" in status_param["type"]

    def test_no_operation_id_fallback(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        # DELETE /pets/{petId} has no operationId
        delete_op = next(t for t in manifest["tools"] if t["method"] == "DELETE")
        assert delete_op["func_name"] == "delete_pets_by_pet_id"

    def test_get_capability(self):
        compiler = OpenAPICompiler("petstore", "inline")
        compiler.compile(spec=PETSTORE_SPEC)
        capability, summaries = compiler.get_capability()

        assert capability.tool_name == "petstore"
        assert len(capability.actions) == 4
        assert "LIST_PETS" in summaries

    def test_get_capability_with_filtered_tools(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        filtered = [t for t in manifest["tools"] if t["func_name"] == "list_pets"]
        capability, summaries = compiler.get_capability(tools=filtered)

        assert capability.tool_name == "petstore"
        assert len(capability.actions) == 1
        assert "LIST_PETS" in summaries
        assert "CREATE_PET" not in summaries

    def test_get_api_docs(self):
        compiler = OpenAPICompiler("petstore", "inline")
        compiler.compile(spec=PETSTORE_SPEC)
        docs = compiler.get_api_docs()

        assert "petstore:list_pets" in docs
        assert "petstore:create_pet" in docs
        assert "await petstore." in docs["petstore:list_pets"]

    def test_get_api_docs_with_filtered_tools(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        filtered = [t for t in manifest["tools"] if t["func_name"] == "list_pets"]
        docs = compiler.get_api_docs(tools=filtered)

        assert "petstore:list_pets" in docs
        assert "petstore:create_pet" not in docs

    def test_python_signature(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        show_pet = next(t for t in manifest["tools"] if t["func_name"] == "show_pet_by_id")
        sig = show_pet["python_signature"]
        assert "show_pet_by_id(" in sig
        assert "petId: string" in sig

    def test_base_url_from_spec(self):
        compiler = OpenAPICompiler("petstore", "inline")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        assert manifest["base_url"] == "https://petstore.example.com/v1"

    def test_base_url_override(self):
        compiler = OpenAPICompiler("petstore", "inline", base_url="https://custom.api.com")
        manifest = compiler.compile(spec=PETSTORE_SPEC)
        assert manifest["base_url"] == "https://custom.api.com"

    def test_missing_paths_raises(self):
        bad_spec = {"openapi": "3.0.3", "info": {"title": "Bad", "version": "1.0"}}
        compiler = OpenAPICompiler("bad", "inline")
        with pytest.raises(Exception, match="no 'paths' key"):
            compiler.compile(spec=bad_spec)

    def test_missing_base_url_raises(self):
        spec_no_servers = dict(PETSTORE_SPEC)
        spec_no_servers = {**PETSTORE_SPEC, "servers": []}
        compiler = OpenAPICompiler("petstore", "inline")
        with pytest.raises(Exception, match="No base URL"):
            compiler.compile(spec=spec_no_servers)


class TestCaching:

    def test_cache_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cortex._engine.api.compiler.CACHE_DIR", tmp_path)

        compiler = OpenAPICompiler("petstore", "inline")
        compiler._cache_dir = tmp_path / "petstore_test"
        manifest = compiler.compile(spec=PETSTORE_SPEC)

        # Load from cache
        compiler2 = OpenAPICompiler("petstore", "inline")
        compiler2._cache_dir = tmp_path / "petstore_test"
        cached = compiler2.load_cache()

        assert cached is not None
        assert cached["tool_name"] == "petstore"
        assert len(cached["tools"]) == len(manifest["tools"])

    def test_clear_cache(self, tmp_path):
        compiler = OpenAPICompiler("petstore", "inline")
        compiler._cache_dir = tmp_path / "petstore_test"
        compiler.compile(spec=PETSTORE_SPEC)

        assert (tmp_path / "petstore_test" / "manifest.json").exists()
        compiler.clear_cache()
        assert not (tmp_path / "petstore_test").exists()


class TestNameHelpers:

    @pytest.mark.parametrize("input_id,expected", [
        ("listPets", "list_pets"),
        ("getApiV2UsersList", "get_api_v2_users_list"),
        ("create-user", "create_user"),
        ("showPetById", "show_pet_by_id"),
        ("__weird__", "weird"),
    ])
    def test_sanitize_name(self, input_id, expected):
        assert OpenAPICompiler._sanitize_name(input_id) == expected

    @pytest.mark.parametrize("method,path,expected", [
        ("get", "/users/{id}", "get_users_by_id"),
        ("post", "/orders", "post_orders"),
        ("delete", "/items/{itemId}", "delete_items_by_item_id"),
        ("get", "/v2/users/{userId}/posts", "get_v2_users_by_user_id_posts"),
    ])
    def test_path_to_name(self, method, path, expected):
        assert OpenAPICompiler._path_to_name(method, path) == expected


class TestRefResolution:

    def test_resolve_simple_ref(self):
        spec = {
            "components": {
                "schemas": {
                    "Pet": {"type": "object", "properties": {"name": {"type": "string"}}}
                }
            }
        }
        result = _resolve_ref(spec, "#/components/schemas/Pet")
        assert result["type"] == "object"

    def test_deep_resolve(self):
        spec = {
            "components": {
                "schemas": {
                    "Pet": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "owner": {"$ref": "#/components/schemas/Owner"},
                        },
                    },
                    "Owner": {"type": "object", "properties": {"email": {"type": "string"}}},
                }
            }
        }
        schema = {"$ref": "#/components/schemas/Pet"}
        result = _deep_resolve(spec, schema)
        assert result["type"] == "object"
        assert result["properties"]["owner"]["type"] == "object"


class TestLoadSpec:

    def test_load_json_file(self, tmp_path):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps(PETSTORE_SPEC))
        loaded = _load_spec(str(spec_path))
        assert loaded["info"]["title"] == "Petstore"

    def test_load_missing_file_raises(self):
        with pytest.raises(Exception, match="not found"):
            _load_spec("/nonexistent/path/spec.json")


class TestAPIToolInspect:

    def test_inspect_non_verbose(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cortex._engine.api.compiler.CACHE_DIR", tmp_path)

        spec_path = tmp_path / "petstore.json"
        spec_path.write_text(json.dumps(PETSTORE_SPEC))

        from cortex.connections.api import APITool
        api = APITool(spec=str(spec_path), name="petstore", cache=False)
        result = api.inspect()

        assert result["tool"] == "petstore"
        assert result["total"] == 4
        assert "list_pets" in result["methods"]
        assert "create_pet" in result["methods"]
        assert "show_pet_by_id" in result["methods"]

    def test_inspect_verbose(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cortex._engine.api.compiler.CACHE_DIR", tmp_path)

        spec_path = tmp_path / "petstore.json"
        spec_path.write_text(json.dumps(PETSTORE_SPEC))

        from cortex.connections.api import APITool
        api = APITool(spec=str(spec_path), name="petstore", cache=False)
        result = api.inspect(verbose=True)

        assert result["total"] == 4
        assert isinstance(result["methods"], list)
        assert isinstance(result["methods"][0], dict)
        assert "name" in result["methods"][0]
        assert "description" in result["methods"][0]
        # Verbose descriptions include HTTP method and path
        descs = [m["description"] for m in result["methods"]]
        assert any("GET" in d for d in descs)

    def test_inspect_class_method(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cortex._engine.api.compiler.CACHE_DIR", tmp_path)

        spec_path = tmp_path / "petstore.json"
        spec_path.write_text(json.dumps(PETSTORE_SPEC))

        from cortex.connections.api import APITool
        result = APITool.inspect(spec=str(spec_path), cache=False)

        assert "methods" in result
        assert result["total"] == 4

    def test_inspect_with_allow_filter(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cortex._engine.api.compiler.CACHE_DIR", tmp_path)

        spec_path = tmp_path / "petstore.json"
        spec_path.write_text(json.dumps(PETSTORE_SPEC))

        from cortex.connections.api import APITool
        api = APITool(
            spec=str(spec_path),
            name="petstore",
            allow=["list_pets", "show_pet_by_id"],
            cache=False,
        )
        result = api.inspect()
        # inspect() shows all endpoints (allow= only filters at compile time)
        assert result["total"] == 4


class TestAPIToolDeriveName:

    def test_url_derive(self):
        from cortex.connections.api import APITool
        assert APITool._derive_name("https://api.stripe.com/v1/openapi.json") == "stripe"
        assert APITool._derive_name("https://petstore3.swagger.io/spec.json") == "petstore3"

    def test_file_derive(self):
        from cortex.connections.api import APITool
        assert APITool._derive_name("./petstore_openapi.json") == "petstore"
        assert APITool._derive_name("/path/to/my_api_spec.yaml") == "my_api"
        assert APITool._derive_name("stripe.json") == "stripe"


class TestAPIToolImport:

    def test_import_from_delfhos(self):
        from delfhos import APITool
        assert APITool is not None
        assert hasattr(APITool, "inspect")
        assert hasattr(APITool, "compile")

    def test_import_from_delfhos_tools(self):
        from delfhos.tools import APITool
        assert APITool is not None
