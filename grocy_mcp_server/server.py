"""
Grocy MCP Server — Self-built MCP server for Grocy household inventory management.
Covers: stock, products, locations, shopping list, chores, quantities, stores.

Tool names use the grocy_ prefix per MCP best practices so they never collide
with tools from other MCP servers.
"""

import os
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

# --- Config ---
# Read lazily so importing the package (tests, tooling, --help) never requires
# a live instance. main() validates before serving.
GROCY_URL = os.environ.get("GROCY_URL", "").rstrip("/")
GROCY_KEY = os.environ.get("GROCY_KEY", "")

MISSING_CONFIG_MESSAGE = (
    "GROCY_URL and GROCY_KEY must be set. Point GROCY_URL at your Grocy base URL "
    "(for example https://grocy.example.com) and GROCY_KEY at an API key from "
    "Grocy -> Settings -> Manage API keys."
)


def _headers() -> dict:
    if not GROCY_URL or not GROCY_KEY:
        raise ToolError(MISSING_CONFIG_MESSAGE)
    return {
        "GROCY-API-KEY": GROCY_KEY,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# Location IDs are instance-specific — never hardcode them in docstrings.
# Use grocy_list_locations to resolve valid IDs at call time.

mcp = FastMCP("grocy")

# --- Annotation presets ---
ANNOT_READ = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
ANNOT_WRITE = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
ANNOT_DESTRUCTIVE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
ANNOT_OVERWRITE = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}


# --- Helpers ---
def _request(method: str, path: str, params: dict | None = None, data: dict | None = None) -> Any:
    """Single HTTP entry point with actionable error handling."""
    try:
        r = httpx.request(
            method,
            f"{GROCY_URL}{path}",
            headers=_headers(),
            params=params,
            json=data,
            timeout=30,
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:200]
        raise ToolError(
            f"Grocy API returned {e.response.status_code} for {path}: {detail}. "
            f"Verify the ID exists (use the grocy_list_* tools to look it up) "
            f"and that the API key is valid."
        )
    except httpx.RequestError as e:
        raise ToolError(
            f"Cannot reach Grocy at {GROCY_URL}: {e}. "
            f"Check that the Grocy service is running and reachable."
        )
    return r.json() if r.text else {}


def _get(path: str, params: dict | None = None) -> Any:
    return _request("GET", path, params=params)


def _post(path: str, data: dict | None = None) -> Any:
    return _request("POST", path, data=data or {})


def _put(path: str, data: dict | None = None) -> Any:
    return _request("PUT", path, data=data or {})


def _delete(path: str) -> Any:
    return _request("DELETE", path)


def _location_map() -> dict:
    return {loc["id"]: loc["name"] for loc in _get("/api/objects/locations")}


# ============================================================
# STOCK
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_get_stock() -> str:
    """Get all products currently in stock with quantities and next due dates."""
    items = _get("/api/stock")
    if not items:
        return "No products in stock."
    loc_map = _location_map()
    lines = ["## Current Stock", ""]
    for item in items:
        prod = item.get("product", {})
        name = prod.get("name", "?")
        qty = item.get("amount", 0)
        opened = item.get("amount_opened", 0)
        due = item.get("best_before_date", "")
        loc_id = prod.get("location_id")
        location = loc_map.get(loc_id, str(loc_id)) if loc_id else "?"
        due_str = f" (due: {due})" if due and due != "2999-12-31" else ""
        opened_str = f" [{opened} opened]" if opened else ""
        lines.append(f"- **{name}**: {qty} @ {location}{opened_str}{due_str}")
    return "\n".join(lines)


VOLATILE_CATEGORIES = (
    ("overdue_products", "Overdue"),
    ("due_products", "Due soon"),
    ("expired_products", "Expired"),
    ("missing_products", "Missing"),
)


@mcp.tool(annotations=ANNOT_READ)
def grocy_get_stock_volatile() -> str:
    """Get products that are due soon, overdue, expired, or currently missing."""
    payload = _get("/api/stock/volatile")
    if not payload:
        return "No volatile products."

    # Grocy 4.x returns one object keyed by category, each holding a list of
    # stock entries. Older/other shapes have been seen as a flat list, so both
    # are handled rather than assuming one.
    if isinstance(payload, list):
        buckets = [("Products", payload)]
    elif isinstance(payload, dict):
        buckets = [(label, payload.get(key) or []) for key, label in VOLATILE_CATEGORIES]
    else:
        return f"Unexpected response from /api/stock/volatile: {type(payload).__name__}"

    lines: list[str] = []
    total = 0
    for label, entries in buckets:
        if not entries:
            continue
        lines.append(f"### {label} ({len(entries)})")
        for item in entries:
            if not isinstance(item, dict):
                lines.append(f"- {item}")
                total += 1
                continue
            prod = item.get("product") or {}
            name = prod.get("name") or item.get("product_name") or f"product {item.get('product_id', '?')}"
            amount = item.get("amount", item.get("amount_aggregated"))
            due = item.get("best_before_date") or ""
            bits = []
            if amount is not None:
                bits.append(f"{amount} in stock")
            if due and due != "2999-12-31":
                bits.append(f"best before {due}")
            suffix = f" ({', '.join(bits)})" if bits else ""
            lines.append(f"- **{name}**{suffix}")
            total += 1
        lines.append("")

    if not total:
        return "No volatile products."
    return "## Due Soon / Overdue / Expired / Missing\n\n" + "\n".join(lines).rstrip()


@mcp.tool(annotations=ANNOT_READ)
def grocy_get_product_stock(product_id: int) -> str:
    """Get stock details for a specific product."""
    r = _get(f"/api/stock/products/{product_id}")
    if not r:
        return "Product not found or not in stock."
    prod = r.get("product", {})
    name = prod.get("name", "?")
    qty = r.get("amount", 0)
    opened = r.get("amount_opened", 0)
    due = r.get("best_before_date", "")
    loc_map = _location_map()
    loc_id = prod.get("location_id")
    location = loc_map.get(loc_id, str(loc_id)) if loc_id else "?"
    lines = [f"**{name}**: {qty} @ {location}"]
    if opened:
        lines.append(f"Opened: {opened}")
    if due and due != "2999-12-31":
        lines.append(f"Best before: {due}")
    return "\n".join(lines)


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_add_stock(product_id: int, amount: float, location_id: int, best_before_date: str = "") -> str:
    """Add stock for a product. Use grocy_list_locations to get valid location_id values."""
    data = {"amount": amount, "location_id": location_id}
    if best_before_date:
        data["best_before_date"] = best_before_date
    _post(f"/api/stock/products/{product_id}/add", data)
    return f"Added {amount} of product {product_id} to location {location_id}"


@mcp.tool(annotations=ANNOT_DESTRUCTIVE)
def grocy_consume_stock(product_id: int, amount: float = 1) -> str:
    """Consume (remove) stock for a product. This permanently reduces stock."""
    _post(f"/api/stock/products/{product_id}/consume", {"amount": amount})
    return f"Consumed {amount} of product {product_id}"


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_transfer_stock(product_id: int, amount: float, location_from: int, location_to: int) -> str:
    """Transfer stock between locations. Use grocy_list_locations to get valid IDs."""
    _post(f"/api/stock/products/{product_id}/transfer", {
        "amount": amount,
        "location_id_from": location_from,
        "location_id_to": location_to,
    })
    return f"Transferred {amount} of product {product_id} from {location_from} to {location_to}"


@mcp.tool(annotations=ANNOT_OVERWRITE)
def grocy_set_stock(product_id: int, new_amount: float, location_id: int) -> str:
    """Set stock to a specific amount (inventory adjustment). Overwrites the current count."""
    _post(f"/api/stock/products/{product_id}/inventory", {
        "new_amount": new_amount,
        "location_id": location_id,
    })
    return f"Set product {product_id} stock to {new_amount}"


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_open_stock(product_id: int, amount: float = 1) -> str:
    """Mark stock as opened."""
    _post(f"/api/stock/products/{product_id}/open", {"amount": amount})
    return f"Opened {amount} of product {product_id}"


# ============================================================
# PRODUCTS (via /objects API)
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_products(search: str = "", limit: int = 50) -> str:
    """List products. Optional search by name."""
    params = {}
    if search:
        params["query[]"] = f"(name={search})"
    params["limit"] = limit
    items = _get("/api/objects/products", params)
    if not items:
        return "No products found."
    lines = []
    for p in items:
        name = p.get("name", "?")
        pid = p.get("id", "?")
        group = p.get("product_group_id", "")
        location = p.get("location_id", "")
        lines.append(f"- {name} (id: {pid}, group: {group}, location: {location})")
    return "\n".join(lines)


@mcp.tool(annotations=ANNOT_READ)
def grocy_get_product(product_id: int) -> str:
    """Get full product details by ID."""
    p = _get(f"/api/objects/products/{product_id}")
    if not p:
        return "Product not found."
    lines = [f"## {p.get('name', '?')}"]
    for k, v in p.items():
        if v and k not in ("userfields",) and not k.startswith("_"):
            lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_create_product(name: str, product_group_id: int = 0, location_id: int = 0, unit_id: int = 0) -> str:
    """Create a new product. Use grocy_list_product_groups / grocy_list_locations / grocy_list_quantity_units for valid IDs."""
    data = {"name": name}
    if product_group_id:
        data["product_group_id"] = product_group_id
    if location_id:
        data["location_id"] = location_id
    if unit_id:
        data["qu_id_stock"] = unit_id
    r = _post("/api/objects/products", data)
    pid = r.get("id", "unknown")
    return f"Created product: **{name}** (id: {pid})"


@mcp.tool(annotations=ANNOT_DESTRUCTIVE)
def grocy_delete_product(product_id: int) -> str:
    """Delete a product by ID. This cannot be undone."""
    _delete(f"/api/objects/products/{product_id}")
    return f"Deleted product {product_id}"


# ============================================================
# SHOPPING LIST
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_get_shopping_list() -> str:
    """Get all items on the shopping list."""
    items = _get("/api/objects/shopping_list")
    if not items:
        return "Shopping list is empty."
    lines = ["## Shopping List", ""]
    for item in items:
        name = item.get("product_name") or item.get("note", "?")
        qty = item.get("amount", 1)
        checked = "✅" if item.get("done", 0) == 1 else "⬜"
        sid = item.get("id", "?")
        lines.append(f"{checked} {qty}x {name} (id: {sid})")
    return "\n".join(lines)


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_add_to_shopping_list(product_id: int, amount: int = 1) -> str:
    """Add a product to the shopping list."""
    _post("/api/objects/shopping_list", {"product_id": product_id, "amount": amount})
    return f"Added product {product_id} (x{amount}) to shopping list"


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_add_note_to_shopping_list(note: str, amount: int = 1) -> str:
    """Add a free-text note to the shopping list (no product link needed)."""
    _post("/api/objects/shopping_list", {"note": note, "amount": amount})
    return f"Added note: {note}"


@mcp.tool(annotations=ANNOT_DESTRUCTIVE)
def grocy_remove_from_shopping_list(shopping_list_item_id: int) -> str:
    """Remove an item from the shopping list by its shopping_list ID."""
    _delete(f"/api/objects/shopping_list/{shopping_list_item_id}")
    return f"Removed item {shopping_list_item_id} from shopping list"


@mcp.tool(annotations=ANNOT_DESTRUCTIVE)
def grocy_clear_shopping_list() -> str:
    """Clear all items from the shopping list. This cannot be undone."""
    _post("/api/stock/shoppinglist/clear", {})
    return "Shopping list cleared"


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_add_missing_to_shopping_list(shopping_list_id: int = 1) -> str:
    """Add products below minimum stock amount to the shopping list."""
    _post(f"/api/stock/shoppinglist/add-missing-products", {"shopping_list_id": shopping_list_id})
    return "Added missing products to shopping list"


# ============================================================
# LOCATIONS
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_locations() -> str:
    """List all storage locations."""
    items = _get("/api/objects/locations")
    if not items:
        return "No locations found."
    lines = []
    for loc in items:
        lines.append(f"- {loc.get('name', '?')} (id: {loc.get('id', '?')})")
    return "\n".join(lines)


# ============================================================
# PRODUCT GROUPS
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_product_groups() -> str:
    """List all product groups/categories."""
    items = _get("/api/objects/product_groups")
    if not items:
        return "No product groups found."
    lines = []
    for g in items:
        lines.append(f"- {g.get('name', '?')} (id: {g.get('id', '?')})")
    return "\n".join(lines)


# ============================================================
# QUANTITY UNITS
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_quantity_units() -> str:
    """List all quantity units."""
    items = _get("/api/objects/quantity_units")
    if not items:
        return "No quantity units found."
    lines = []
    for u in items:
        name = u.get("name", "?")
        abbr = u.get("name_plural", u.get("name", ""))
        lines.append(f"- {name} ({abbr}) (id: {u.get('id', '?')})")
    return "\n".join(lines)


# ============================================================
# STORES
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_shopping_locations() -> str:
    """List all stores/shopping locations."""
    items = _get("/api/objects/shopping_locations")
    if not items:
        return "No stores found."
    lines = []
    for s in items:
        lines.append(f"- {s.get('name', '?')} (id: {s.get('id', '?')})")
    return "\n".join(lines)


# ============================================================
# CHORES
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_chores() -> str:
    """List all household chores."""
    items = _get("/api/objects/chores")
    if not items:
        return "No chores found."
    lines = []
    for c in items:
        lines.append(f"- {c.get('name', '?')} (id: {c.get('id', '?')})")
    return "\n".join(lines)


# ============================================================
# RECIPES (limited — Grocy recipe API is basic)
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_list_grocy_recipes() -> str:
    """List recipes stored in Grocy (basic — use the mealie MCP server for full recipe management)."""
    items = _get("/api/objects/recipes")
    if not items:
        return "No recipes in Grocy."
    lines = []
    for r in items:
        lines.append(f"- {r.get('name', '?')} (id: {r.get('id', '?')})")
    return "\n".join(lines)


@mcp.tool(annotations=ANNOT_WRITE)
def grocy_add_recipe_to_shopping_list(recipe_id: int, shopping_list_id: int = 1) -> str:
    """Add missing products from a Grocy recipe to the shopping list."""
    _post(f"/api/recipes/{recipe_id}/add-not-fulfilled-products-to-shoppinglist", {
        "shopping_list_id": shopping_list_id
    })
    return f"Added missing recipe {recipe_id} products to shopping list"


# ============================================================
# SYSTEM
# ============================================================

@mcp.tool(annotations=ANNOT_READ)
def grocy_get_system_info() -> str:
    """Get Grocy system info (version, etc.)."""
    r = _get("/api/system/info")
    lines = ["## Grocy System Info"]
    for k, v in r.items():
        if v:
            lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

# ============================================================
# MAIN
# ============================================================

def main() -> None:
    """Entry point for the `grocy-mcp-server` console script."""
    if not GROCY_URL or not GROCY_KEY:
        raise SystemExit(MISSING_CONFIG_MESSAGE)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

