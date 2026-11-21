"""Behaviour tests for the Grocy MCP server.

All tests run against a fake Grocy backend (``httpx.request`` is monkeypatched)
— no network access. Response shapes follow real Grocy 4.7.1 captures;
Grocy 3.x fallback shapes are covered where the server still supports them.
"""

import asyncio
import re
from pathlib import Path

import httpx
import pytest
from fastmcp.exceptions import ToolError

import server

REPO_ROOT = Path(__file__).resolve().parent.parent


def _resp(method: str, url: str, status: int, payload) -> httpx.Response:
    return httpx.Response(status, json=payload, request=httpx.Request(method, url))


class FakeGrocy:
    """Route-table fake for httpx.request, recording every call."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], tuple[int, object, str | None]] = {}
        self.calls: list[dict] = []

    def route(self, method: str, path: str, payload=None, status: int = 200, body: str | None = None) -> None:
        self.routes[(method.upper(), path)] = (status, payload, body)

    def __call__(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params, "json": json})
        path = url.split("grocy.test", 1)[1] if "grocy.test" in url else url
        key = (method.upper(), path)
        if key in self.routes:
            status, payload, body = self.routes[key]
            if body is not None:
                return httpx.Response(status, text=body, request=httpx.Request(method, url))
            return _resp(method, url, status, payload)
        return _resp(method, url, 404, {"error_message": f"no route for {method} {path}"})


@pytest.fixture
def grocy(monkeypatch) -> FakeGrocy:
    fake = FakeGrocy()
    monkeypatch.setattr(server.httpx, "request", fake)
    return fake


def _tools() -> dict:
    return {t.name: t for t in asyncio.run(server.mcp.list_tools())}


# ---------------------------------------------------------------- tool surface


def test_tool_count_is_26():
    assert len(_tools()) == 26


def test_tool_names_grocy_prefixed():
    for name in _tools():
        assert name.startswith("grocy_"), name


def test_readme_tool_table_matches_server():
    """README tool table must stay in sync with server.py (the release gate)."""
    readme = (REPO_ROOT / "README.md").read_text()
    rows = re.findall(r"^\| `(grocy_\w+)` \|", readme, re.MULTILINE)
    tools = set(_tools())
    assert len(rows) == len(set(rows)), "duplicate rows in README tool table"
    assert set(rows) == tools, f"README/server tool mismatch: {set(rows) ^ tools}"
    assert f"**{len(tools)} tools**" in readme


def test_tool_annotations():
    tools = _tools()
    read_only = {
        "grocy_get_stock", "grocy_get_stock_volatile", "grocy_get_product_stock",
        "grocy_list_products", "grocy_get_product", "grocy_get_shopping_list",
        "grocy_list_locations", "grocy_list_product_groups", "grocy_list_quantity_units",
        "grocy_list_shopping_locations", "grocy_list_chores", "grocy_list_grocy_recipes",
        "grocy_get_system_info",
    }
    destructive = {
        "grocy_consume_stock", "grocy_delete_product",
        "grocy_remove_from_shopping_list", "grocy_clear_shopping_list",
    }
    overwrite = {"grocy_set_stock"}
    assert len(read_only | destructive | overwrite) == 18
    for name in read_only:
        ann = tools[name].annotations
        assert ann is not None and ann.read_only_hint is True, name
    for name in destructive:
        ann = tools[name].annotations
        assert ann is not None and ann.destructive_hint is True, name
    for name in overwrite:
        ann = tools[name].annotations
        assert ann is not None and ann.destructive_hint is True and ann.idempotent_hint is True, name
    for name in set(tools) - read_only - destructive - overwrite:
        ann = tools[name].annotations
        assert ann is not None and ann.read_only_hint is False, name


# ------------------------------------------------- /api/stock/volatile (4.x)


VOLATILE_4X = {
    "due_products": [
        {"amount": 2, "best_before_date": "2026-11-25", "product": {"name": "Milk"}},
    ],
    "overdue_products": [
        {"amount": 5, "best_before_date": "2026-01-01", "product": {"name": "Butter"}},
        {"amount": 1, "best_before_date": "2026-02-02", "product": {"name": "Eggs"}},
    ],
    "expired_products": [],
    "missing_products": [],
}


def test_volatile_grocy4_buckets(grocy):
    """Grocy 4.x returns a dict of buckets — the attmous/grocy-mcp#10 breakage."""
    grocy.route("GET", "/api/stock/volatile", payload=VOLATILE_4X)
    out = server.grocy_get_stock_volatile()
    assert "## Due Soon" in out
    assert "- **Milk**: 2 — best before 2026-11-25" in out
    assert "## Overdue (best before date passed)" in out
    assert "- **Butter**: 5 — best before 2026-01-01" in out
    assert "- **Eggs**: 1 — best before 2026-02-02" in out
    # the failure mode this guards against: raw bucket keys leaking to the user
    assert "due_products" not in out
    assert "overdue_products" not in out


def test_volatile_grocy3_buckets(grocy):
    """Grocy 3.x used expiring_products and had no overdue bucket."""
    grocy.route("GET", "/api/stock/volatile", payload={
        "expiring_products": [
            {"amount": 1, "best_before_date": "2026-11-22", "product": {"name": "Yogurt"}},
        ],
        "expired_products": [
            {"amount": 2, "best_before_date": "2026-01-01", "product": {"name": "Ham"}},
        ],
        "missing_products": [
            {"amount": 1, "product": {"name": "Lost Thing"}},
        ],
    })
    out = server.grocy_get_stock_volatile()
    assert "- **Yogurt**: 1 — best before 2026-11-22" in out
    assert "## Expired" in out and "- **Ham**: 2 — best before 2026-01-01" in out
    assert "## Missing" in out and "- **Lost Thing**: 1" in out
    assert "expiring_products" not in out


def test_volatile_all_buckets_empty(grocy):
    grocy.route("GET", "/api/stock/volatile", payload={
        "due_products": [], "overdue_products": [], "expired_products": [], "missing_products": [],
    })
    assert server.grocy_get_stock_volatile() == "No products due soon, overdue, expired, or missing."


def test_volatile_empty_response(grocy):
    grocy.route("GET", "/api/stock/volatile", payload={})
    assert server.grocy_get_stock_volatile() == "No volatile products."


def test_volatile_flat_list_fallback(grocy):
    """Older versions/mocks returned a flat list of stock entries."""
    grocy.route("GET", "/api/stock/volatile", payload=[
        {"product": {"name": "Eggs"}, "amount": 12, "best_before_date": "2026-11-30"},
        "plain-string-entry",
    ])
    out = server.grocy_get_stock_volatile()
    assert out.startswith("## Due Soon / Overdue / Missing")
    assert "- **Eggs**: 12 — best before 2026-11-30" in out
    assert "- plain-string-entry" in out


def test_volatile_never_prints_date_2999(grocy):
    grocy.route("GET", "/api/stock/volatile", payload={
        "due_products": [], "expired_products": [], "missing_products": [],
        "overdue_products": [{"amount": 3, "best_before_date": "2999-12-31", "product": {"name": "Forever"}}],
    })
    out = server.grocy_get_stock_volatile()
    assert "- **Forever**: 3" in out
    assert "2999-12-31" not in out


def test_volatile_missing_entries_use_amount_missing(grocy):
    """Grocy 4.x missing rows carry amount_missing, not amount (real 4.7.1 shape)."""
    grocy.route("GET", "/api/stock/volatile", payload={
        "due_products": [], "overdue_products": [], "expired_products": [],
        "missing_products": [
            {"id": 1, "name": "Probe Butter", "amount_missing": 5, "is_partly_in_stock": 1,
             "product": {"name": "Probe Butter"}},
        ],
    })
    out = server.grocy_get_stock_volatile()
    assert "## Missing" in out
    assert "- **Probe Butter**: 5 missing" in out
    assert "?" not in out


# ------------------------------------------------- /api/stock/products/{id}


def test_product_stock_grocy4_fields(grocy):
    grocy.route("GET", "/api/stock/products/2", payload={
        "product": {"name": "Butter", "location_id": 4},
        "stock_amount": 15,
        "stock_amount_opened": 1,
        "next_due_date": "2026-09-22",
    })
    grocy.route("GET", "/api/objects/locations", payload=[{"id": 4, "name": "Freezer"}])
    out = server.grocy_get_product_stock(2)
    assert out.splitlines()[0] == "**Butter**: 15 @ Freezer"
    assert "Opened: 1" in out
    assert "Best before: 2026-09-22" in out


def test_product_stock_legacy_fields(grocy):
    grocy.route("GET", "/api/stock/products/5", payload={
        "product": {"name": "Milk", "location_id": 2},
        "amount": 3,
        "amount_opened": 0,
        "best_before_date": "2999-12-31",
    })
    grocy.route("GET", "/api/objects/locations", payload=[{"id": 2, "name": "Fridge"}])
    out = server.grocy_get_product_stock(5)
    assert "**Milk**: 3 @ Fridge" in out
    assert "Best before" not in out  # 2999-12-31 means "no date"


def test_product_stock_not_in_stock(grocy):
    grocy.route("GET", "/api/stock/products/99", payload={})
    assert server.grocy_get_product_stock(99) == "Product not found or not in stock."


# ------------------------------------------------------------- create/delete


def test_create_product_defaults_to_first_location_and_unit(grocy):
    grocy.route("GET", "/api/objects/locations", payload=[{"id": 2, "name": "Fridge"}])
    grocy.route("GET", "/api/objects/quantity_units", payload=[{"id": 2, "name": "Piece"}])
    grocy.route("POST", "/api/objects/products", payload={"created_object_id": "42"})
    out = server.grocy_create_product(name="Oatmeal")
    assert out == "Created product: **Oatmeal** (id: 42)"
    posts = [c for c in grocy.calls if c["method"] == "POST"]
    assert len(posts) == 1
    assert posts[0]["json"] == {
        "name": "Oatmeal", "location_id": 2, "qu_id_purchase": 2, "qu_id_stock": 2,
    }


def test_create_product_explicit_ids_skip_lookups(grocy):
    grocy.route("POST", "/api/objects/products", payload={"created_object_id": "7"})
    out = server.grocy_create_product(name="Rice", location_id=5, unit_id=3, product_group_id=9)
    assert out == "Created product: **Rice** (id: 7)"
    assert [c["method"] for c in grocy.calls] == ["POST"]
    assert grocy.calls[0]["json"] == {
        "name": "Rice", "product_group_id": 9, "location_id": 5,
        "qu_id_purchase": 3, "qu_id_stock": 3,
    }


def test_create_product_legacy_id_response(grocy):
    grocy.route("GET", "/api/objects/locations", payload=[{"id": 2, "name": "Fridge"}])
    grocy.route("GET", "/api/objects/quantity_units", payload=[{"id": 2, "name": "Piece"}])
    grocy.route("POST", "/api/objects/products", payload={"id": 11})
    out = server.grocy_create_product(name="Beans")
    assert out == "Created product: **Beans** (id: 11)"


def test_delete_product(grocy):
    grocy.route("DELETE", "/api/objects/products/3", payload={})
    assert server.grocy_delete_product(3) == "Deleted product 3"
    assert grocy.calls[0]["method"] == "DELETE"


# ---------------------------------------------------------------- stock reads


def test_get_stock_formats_lines(grocy):
    grocy.route("GET", "/api/stock", payload=[
        {"amount": 1.5, "amount_opened": 0, "best_before_date": "2026-11-24",
         "product": {"name": "Milk", "location_id": 2}},
        {"amount": 12, "amount_opened": 2, "best_before_date": "2999-12-31",
         "product": {"name": "Eggs", "location_id": 2}},
    ])
    grocy.route("GET", "/api/objects/locations", payload=[{"id": 2, "name": "Fridge"}])
    out = server.grocy_get_stock()
    assert "- **Milk**: 1.5 @ Fridge (due: 2026-11-24)" in out
    assert "- **Eggs**: 12 @ Fridge [2 opened]" in out
    assert "2999" not in out


def test_get_stock_empty(grocy):
    grocy.route("GET", "/api/stock", payload=[])
    assert server.grocy_get_stock() == "No products in stock."


def test_list_products_search_param(grocy):
    grocy.route("GET", "/api/objects/products", payload=[{"id": 1, "name": "Oat Crisp", "product_group_id": 5, "location_id": 3}])
    out = server.grocy_list_products(search="Oat", limit=10)
    assert "- Oat Crisp (id: 1, group: 5, location: 3)" in out
    assert grocy.calls[0]["params"] == {"query[]": "(name=Oat)", "limit": 10}


# --------------------------------------------------------------- system info


def test_system_info_formats_nested_version(grocy):
    grocy.route("GET", "/api/system/info", payload={
        "grocy_version": {"Version": "4.7.1", "ReleaseDate": "2026-09-04"},
        "php_version": "8.5.13",
        "os": "",
    })
    out = server.grocy_get_system_info()
    assert "- **grocy_version**: v4.7.1 (released 2026-09-04)" in out
    assert "- **php_version**: 8.5.13" in out
    assert "os" not in out  # empty values are skipped


# ----------------------------------------------------------- shopping list


def test_shopping_list_resolves_product_names_grocy4(grocy):
    """Grocy 4.x rows carry only product_id — names must be resolved, never 'None'."""
    grocy.route("GET", "/api/objects/shopping_list", payload=[
        {"id": 7, "product_id": 1, "note": None, "amount": 2, "done": 0},
        {"id": 8, "note": "paper towels", "amount": 1, "done": 1},
    ])
    grocy.route("GET", "/api/objects/products", payload=[{"id": 1, "name": "Milk"}])
    out = server.grocy_get_shopping_list()
    assert "⬜ 2x Milk (id: 7)" in out
    assert "✅ 1x paper towels (id: 8)" in out
    assert "None" not in out


def test_shopping_list_unknown_product_id_fallback(grocy):
    grocy.route("GET", "/api/objects/shopping_list", payload=[
        {"id": 9, "product_id": 99, "amount": 1, "done": 0},
    ])
    grocy.route("GET", "/api/objects/products", payload=[])
    out = server.grocy_get_shopping_list()
    assert "⬜ 1x product #99 (id: 9)" in out
    assert "None" not in out


def test_shopping_list_legacy_embedded_names(grocy):
    """Older versions embedded product_name — no extra products lookup then."""
    grocy.route("GET", "/api/objects/shopping_list", payload=[
        {"id": 7, "product_id": 1, "product_name": "Milk", "amount": 2, "done": 0},
    ])
    out = server.grocy_get_shopping_list()
    assert "⬜ 2x Milk (id: 7)" in out
    assert [c["url"] for c in grocy.calls] == ["http://grocy.test/api/objects/shopping_list"]


def test_shopping_list_empty(grocy):
    grocy.route("GET", "/api/objects/shopping_list", payload=[])
    assert server.grocy_get_shopping_list() == "Shopping list is empty."


def test_add_note_and_remove(grocy):
    grocy.route("POST", "/api/objects/shopping_list", payload={})
    grocy.route("DELETE", "/api/objects/shopping_list/9", payload={})
    assert "Added note: eggs" in server.grocy_add_note_to_shopping_list("eggs")
    assert server.grocy_remove_from_shopping_list(9) == "Removed item 9 from shopping list"
    assert grocy.calls[1]["method"] == "DELETE"


# ------------------------------------------------------------- error paths


def test_http_error_becomes_toolerror(grocy):
    # no route registered → fake returns 404
    with pytest.raises(ToolError) as excinfo:
        server.grocy_get_product(999)
    msg = str(excinfo.value)
    assert "404" in msg and "/api/objects/products/999" in msg


def test_connection_error_becomes_toolerror(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.RequestError(
            "connection refused",
            request=httpx.Request("GET", "http://grocy.test/api/system/info"),
        )

    monkeypatch.setattr(server.httpx, "request", boom)
    with pytest.raises(ToolError) as excinfo:
        server.grocy_get_system_info()
    assert "Cannot reach Grocy" in str(excinfo.value)
