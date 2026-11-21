"""Behavioural tests for grocy-mcp-server.

These run against a stubbed transport: no live Grocy instance is required.
The point is to pin the response-shape handling, especially /api/stock/volatile
which changed shape in Grocy 4.x and silently broke other servers.
"""

import pytest

from grocy_mcp_server import server


@pytest.fixture
def grocy(monkeypatch):
    """Capture HTTP calls and serve canned responses, keyed by path."""

    calls = []
    responses = {}

    def fake_request(method, path, params=None, data=None):
        calls.append({"method": method, "path": path, "params": params, "data": data})
        value = responses.get(path)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(server, "_request", fake_request)
    return {"calls": calls, "responses": responses}


# --------------------------------------------------------------------------
# /api/stock/volatile — the Grocy 4.x shape
# --------------------------------------------------------------------------

VOLATILE_4X = {
    "due_products": [],
    "overdue_products": [
        {
            "amount": 15,
            "best_before_date": "2026-09-22",
            "product_id": 2,
            "product": {"id": 2, "name": "Butter"},
        },
        {
            "amount": 4,
            "best_before_date": "2026-09-22",
            "product_id": 7,
            "product": {"id": 7, "name": "Ravioli"},
        },
    ],
    "expired_products": [],
    "missing_products": [
        {"amount": 0, "product_id": 9, "product": {"id": 9, "name": "Milk"}}
    ],
}


def test_volatile_4x_renders_overdue_products(grocy):
    grocy["responses"]["/api/stock/volatile"] = VOLATILE_4X

    out = server.grocy_get_stock_volatile()

    # The regression this guards: iterating the top-level dict yielded the key
    # names ("due_products", ...) instead of the products inside them.
    assert "Butter" in out
    assert "Ravioli" in out
    assert "Milk" in out
    assert "due_products" not in out
    assert "overdue_products" not in out


def test_volatile_4x_groups_by_category_and_counts(grocy):
    grocy["responses"]["/api/stock/volatile"] = VOLATILE_4X

    out = server.grocy_get_stock_volatile()

    assert "### Overdue (2)" in out
    assert "### Missing (1)" in out
    # Empty categories are omitted rather than printed as headings.
    assert "### Due soon (0)" not in out


def test_volatile_4x_includes_amount_and_due_date(grocy):
    grocy["responses"]["/api/stock/volatile"] = VOLATILE_4X

    out = server.grocy_get_stock_volatile()

    assert "15 in stock" in out
    assert "best before 2026-09-22" in out


def test_volatile_sentinel_due_date_is_hidden(grocy):
    grocy["responses"]["/api/stock/volatile"] = {
        "due_products": [
            {
                "amount": 1,
                "best_before_date": "2999-12-31",
                "product": {"name": "Rice"},
            }
        ],
        "overdue_products": [],
        "expired_products": [],
        "missing_products": [],
    }

    out = server.grocy_get_stock_volatile()

    assert "Rice" in out
    assert "2999-12-31" not in out


def test_volatile_flat_list_shape_still_works(grocy):
    grocy["responses"]["/api/stock/volatile"] = [
        {"amount": 2, "best_before_date": "2026-10-01", "product": {"name": "Eggs"}}
    ]

    out = server.grocy_get_stock_volatile()

    assert "Eggs" in out
    assert "2 in stock" in out


def test_volatile_empty_everywhere(grocy):
    grocy["responses"]["/api/stock/volatile"] = {
        "due_products": [],
        "overdue_products": [],
        "expired_products": [],
        "missing_products": [],
    }

    assert server.grocy_get_stock_volatile() == "No volatile products."


def test_volatile_missing_product_name_falls_back_to_id(grocy):
    grocy["responses"]["/api/stock/volatile"] = {
        "due_products": [],
        "overdue_products": [{"amount": 1, "product_id": 42, "product": {}}],
        "expired_products": [],
        "missing_products": [],
    }

    out = server.grocy_get_stock_volatile()

    assert "product 42" in out


# --------------------------------------------------------------------------
# Stock listing
# --------------------------------------------------------------------------

def test_get_stock_resolves_location_names(grocy):
    grocy["responses"]["/api/stock"] = [
        {
            "amount": 3,
            "amount_opened": 1,
            "best_before_date": "2026-12-01",
            "product": {"name": "Yogurt", "location_id": 2},
        }
    ]
    grocy["responses"]["/api/objects/locations"] = [
        {"id": 2, "name": "Fridge"},
        {"id": 3, "name": "Freezer"},
    ]

    out = server.grocy_get_stock()

    assert "Yogurt" in out
    assert "@ Fridge" in out
    assert "1 opened" in out


def test_get_stock_empty(grocy):
    grocy["responses"]["/api/stock"] = []

    assert server.grocy_get_stock() == "No products in stock."


# --------------------------------------------------------------------------
# Shopping list
# --------------------------------------------------------------------------

def test_shopping_list_marks_checked_items(grocy):
    grocy["responses"]["/api/objects/shopping_list"] = [
        {"id": 1, "product_name": "Bread", "amount": 2, "done": 1},
        {"id": 2, "note": "Stamps", "amount": 1, "done": 0},
    ]

    out = server.grocy_get_shopping_list()

    assert "Bread" in out and "Stamps" in out
    assert out.count("\u2705") == 1
    assert out.count("\u2b1c") == 1


def test_shopping_list_uses_note_when_no_product(grocy):
    grocy["responses"]["/api/objects/shopping_list"] = [
        {"id": 5, "note": "Cat food", "amount": 1, "done": 0}
    ]

    assert "Cat food" in server.grocy_get_shopping_list()


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------

def test_tool_error_surfaces_as_tool_error(grocy):
    from fastmcp.exceptions import ToolError

    grocy["responses"]["/api/stock/products/999"] = ToolError("Grocy API returned 404")

    with pytest.raises(ToolError):
        server.grocy_get_product_stock(999)


# --------------------------------------------------------------------------
# Tool surface contract
# --------------------------------------------------------------------------

def _tools():
    import asyncio

    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


def test_all_tools_are_prefixed():
    """Prefixing avoids collisions when several MCP servers are loaded."""
    names = list(_tools())

    assert len(names) == 26
    assert all(name.startswith("grocy_") for name in names)


def test_read_tools_are_marked_read_only():
    tools = _tools()

    for name in ("grocy_get_stock", "grocy_list_locations", "grocy_get_system_info"):
        annotation = tools[name].annotations
        assert annotation.read_only_hint is True
        assert annotation.destructive_hint is False


def test_destructive_tools_are_marked_destructive():
    """Clients need destructiveHint to gate or confirm these."""
    tools = _tools()

    for name in (
        "grocy_delete_product",
        "grocy_consume_stock",
        "grocy_clear_shopping_list",
        "grocy_remove_from_shopping_list",
    ):
        annotation = tools[name].annotations
        assert annotation.destructive_hint is True
        assert annotation.read_only_hint is False


def test_write_tools_are_neither_read_only_nor_destructive():
    tools = _tools()

    for name in ("grocy_add_stock", "grocy_open_stock", "grocy_add_to_shopping_list"):
        annotation = tools[name].annotations
        assert annotation.read_only_hint is False
        assert annotation.destructive_hint is False


def test_every_tool_has_a_description():
    """The description is what the model reads to choose a tool."""
    for name, tool in _tools().items():
        assert tool.description, f"{name} has no description"

