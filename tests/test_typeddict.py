"""Test TypedDict introspection, docstring fallback, and bare-dict warnings."""
from typing import TypedDict, List, Optional
from delfhos.tool import _describe_type, _extract_signature, _parse_docstring_schema, tool, DelfhosToolWarning, Tool, build_api_signature
import warnings


# --- TypedDicts for testing ---

class Address(TypedDict):
    street: str
    city: str
    zip_code: str

class OrderItem(TypedDict):
    product_id: str
    quantity: int
    price: float

class Order(TypedDict, total=False):
    customer_id: str
    items: List[OrderItem]
    shipping_address: Address


def test_typeddict_expansion():
    print("=== TypedDict expansion ===")
    addr = _describe_type(Address)
    print(f"  Address: {addr}")
    assert "street: string" in addr
    assert "city: string" in addr

    order = _describe_type(Order)
    print(f"  Order: {order}")
    assert "customer_id" in order
    assert "product_id" in order  # nested
    assert "street" in order  # deeply nested

    lst = _describe_type(List[Order])
    print(f"  List[Order]: {lst}")
    assert lst.startswith("array[{")


def test_tool_api_doc_with_typeddict():
    print("\n=== Tool API doc with TypedDict ===")

    @tool
    def create_order(order: Order, priority: str = "normal") -> OrderItem:
        """Create an order."""
        pass

    doc = create_order.api_doc()
    print(doc)
    # Signature should include expanded TypedDict
    assert "customer_id" in doc
    assert "product_id" in doc
    assert "priority: string" in doc


def test_docstring_fallback():
    print("\n=== Docstring fallback ===")

    def process_data(data: dict, mode: str = "fast") -> dict:
        """Run data processing.

        Args:
          data: dict with keys 'id' and 'values'
          mode: str - processing mode

        Returns:
          status: string - ok or error
          count: integer - number processed
        """
        pass

    params, ret = _extract_signature(process_data)
    print(f"  params: {params}")
    print(f"  return: {ret}")
    # data param should get docstring type info since it's bare dict
    assert params["data"]["type"] == "dict with keys 'id' and 'values'"
    # return should have fields from Returns:
    assert "status" in ret
    assert "count" in ret


def test_bare_dict_warning():
    print("\n=== Bare dict warning ===")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        @tool
        def bad_tool(payload: dict) -> dict:
            """Does stuff."""
            pass

    warns = [x for x in w if issubclass(x.category, DelfhosToolWarning)]
    print(f"  Got {len(warns)} DelfhosToolWarning(s):")
    for x in warns:
        print(f"    - {x.message}")
    assert len(warns) >= 2  # one for param, one for return


def test_no_warning_for_typeddict():
    print("\n=== No warning for TypedDict ===")

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")

        @tool
        def good_tool(order: Order) -> Address:
            """Create something."""
            pass

    warns = [x for x in w if issubclass(x.category, DelfhosToolWarning)]
    print(f"  Got {len(warns)} DelfhosToolWarning(s)")
    assert len(warns) == 0, f"Expected no warnings, got: {[str(x.message) for x in warns]}"


def test_plain_types_unchanged():
    print("\n=== Plain types unchanged ===")
    assert _describe_type(str) == "string"
    assert _describe_type(int) == "integer"
    assert _describe_type(float) == "number"
    assert _describe_type(bool) == "boolean"
    assert _describe_type(list) == "array"
    assert _describe_type(List[str]) == "array[string]"
    print("  All plain types OK")


def test_validate_inputs_typeddict_and_array():
    print("\n=== _validate_inputs handles TypedDict/array params ===")
    import asyncio

    @tool
    def process(order: Order, tags: List[str]) -> str:
        """Process an order."""
        return "ok"

    # Wrong type for TypedDict param → should raise ToolException
    try:
        asyncio.get_event_loop().run_until_complete(process.execute(order="not_a_dict", tags=[]))
        assert False, "Should have raised ToolException"
    except Exception as e:
        from delfhos.tool import ToolException
        assert isinstance(e, ToolException), f"Expected ToolException, got {type(e)}: {e}"
        print(f"  TypedDict wrong type caught: {e}")

    # Wrong type for array param → should raise ToolException
    try:
        asyncio.get_event_loop().run_until_complete(process.execute(order={}, tags="not_a_list"))
        assert False, "Should have raised ToolException"
    except Exception as e:
        from delfhos.tool import ToolException
        assert isinstance(e, ToolException), f"Expected ToolException, got {type(e)}: {e}"
        print(f"  array wrong type caught: {e}")


def test_subclass_no_docstring_no_false_description():
    print("\n=== Subclass without docstring no false description ===")
    from delfhos.tool import Tool

    class MyTool(Tool):
        tool_name = "my_tool"
        description = "My custom tool"

        async def execute(self, x: str) -> str:
            return x

    t = MyTool()
    # Should use the class-level description, NOT Tool's own docstring
    assert t.description == "My custom tool"
    assert "Base class" not in t.description
    print(f"  description: '{t.description}' ✓")


if __name__ == "__main__":
    test_typeddict_expansion()
    test_tool_api_doc_with_typeddict()
    test_docstring_fallback()
    test_bare_dict_warning()
    test_no_warning_for_typeddict()
    test_plain_types_unchanged()
    test_validate_inputs_typeddict_and_array()
    test_subclass_no_docstring_no_false_description()
    print("\n✅ ALL TESTS PASSED")
