"""
Grocy MCP Server — Self-built MCP server for Grocy household inventory management.
Covers: stock, products, locations, shopping list, chores, quantities, stores.
"""

import os
import json
from typing import Optional
from fastmcp import FastMCP
import httpx

# --- Config ---
GROCY_URL = os.environ["GROCY_URL"].rstrip("/")
GROCY_KEY = os.environ["GROCY_KEY"]

HEADERS = {
    "GROCY-API-KEY": GROCY_KEY,
    "Accept": "application/json",
    "Content-Type": "application/json",
}

mcp = FastMCP("grocy")


# --- Helpers ---
def _get(path: str, params: dict = None) -> any:
    r = httpx.get(f"{GROCY_URL}{path}", headers=HEADERS, params=params, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}


def _post(path: str, data: dict = None) -> any:
    r = httpx.post(f"{GROCY_URL}{path}", headers=HEADERS, json=data or {}, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}


def _put(path: str, data: dict = None) -> any:
    r = httpx.put(f"{GROCY_URL}{path}", headers=HEADERS, json=data or {}, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}


def _delete(path: str) -> any:
    r = httpx.delete(f"{GROCY_URL}{path}", headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else {}


# ============================================================
# STOCK
# ============================================================

@mcp.tool()
def get_stock() -> str:
    """Get all products currently in stock with quantities and next due dates."""
    items = _get("/api/stock")
    if not items:
        return "No products in stock."
    # Build location map
    loc_map = {loc["id"]: loc["name"] for loc in _get("/api/objects/locations")}
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


@mcp.tool()
def get_stock_volatile() -> str:
    """Get products that are due soon, overdue, expired, or currently missing."""
    items = _get("/api/stock/volatile")
    if not items:
        return "No volatile products."
    lines = ["## Due Soon / Overdue / Missing", ""]
    # Volatile can return mixed types — handle gracefully
    for item in items:
        if isinstance(item, str):
            lines.append(f"- {item}")
            continue
        if isinstance(item, dict):
            prod = item.get("product", {})
            name = prod.get("name", item.get("product_name", "?"))
            due = item.get("best_before_date", "")
            missing = item.get("is_missing", False)
            status = "❌ MISSING" if missing else f"due: {due}"
            lines.append(f"- **{name}**: {status}")
    return "\n".join(lines)


@mcp.tool()
def get_product_stock(product_id: int) -> str:
    """Get stock details for a specific product."""
    r = _get(f"/api/stock/products/{product_id}")
    if not r:
        return "Product not found or not in stock."
    prod = r.get("product", {})
    name = prod.get("name", "?")
    qty = r.get("amount", 0)
    opened = r.get("amount_opened", 0)
    due = r.get("best_before_date", "")
    loc_map = {loc["id"]: loc["name"] for loc in _get("/api/objects/locations")}
    loc_id = prod.get("location_id")
    location = loc_map.get(loc_id, str(loc_id)) if loc_id else "?"
    lines = [f"**{name}**: {qty} @ {location}"]
    if opened:
        lines.append(f"Opened: {opened}")
    if due and due != "2999-12-31":
        lines.append(f"Best before: {due}")
    return "\n".join(lines)


@mcp.tool()
def add_stock(product_id: int, amount: float, location_id: int = 3, best_before_date: str = "") -> str:
    """Add stock for a product. location_id: 3=Fridge, 5=Pantry, 7=LgFreezer, 6=SmFreezer, 4=FridgeFreezer."""
    data = {"amount": amount, "location_id": location_id}
    if best_before_date:
        data["best_before_date"] = best_before_date
    r = _post(f"/api/stock/products/{product_id}/add", data)
    return f"Added {amount} of product {product_id} to location {location_id}"


@mcp.tool()
def consume_stock(product_id: int, amount: float = 1) -> str:
    """Consume (remove) stock for a product."""
    _post(f"/api/stock/products/{product_id}/consume", {"amount": amount})
    return f"Consumed {amount} of product {product_id}"


@mcp.tool()
def transfer_stock(product_id: int, amount: float, location_from: int, location_to: int) -> str:
    """Transfer stock between locations."""
    _post(f"/api/stock/products/{product_id}/transfer", {
        "amount": amount,
        "location_id_from": location_from,
        "location_id_to": location_to,
    })
    return f"Transferred {amount} of product {product_id} from {location_from} to {location_to}"


@mcp.tool()
def set_stock(product_id: int, new_amount: float, location_id: int = 3) -> str:
    """Set stock to a specific amount (inventory adjustment)."""
    _post(f"/api/stock/products/{product_id}/inventory", {
        "new_amount": new_amount,
        "location_id": location_id,
    })
    return f"Set product {product_id} stock to {new_amount}"


@mcp.tool()
def open_stock(product_id: int, amount: float = 1) -> str:
    """Mark stock as opened."""
    _post(f"/api/stock/products/{product_id}/open", {"amount": amount})
    return f"Opened {amount} of product {product_id}"


# ============================================================
# PRODUCTS (via /objects API)
# ============================================================

@mcp.tool()
def list_products(search: str = "", limit: int = 50) -> str:
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


@mcp.tool()
def get_product(product_id: int) -> str:
    """Get full product details by ID."""
    p = _get(f"/api/objects/products/{product_id}")
    if not p:
        return "Product not found."
    lines = [f"## {p.get('name', '?')}"]
    for k, v in p.items():
        if v and k not in ("userfields",) and not k.startswith("_"):
            lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)


@mcp.tool()
def create_product(name: str, product_group_id: int = 0, location_id: int = 3, unit_id: int = 0) -> str:
    """Create a new product."""
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


@mcp.tool()
def delete_product(product_id: int) -> str:
    """Delete a product by ID."""
    _delete(f"/api/objects/products/{product_id}")
    return f"Deleted product {product_id}"


# ============================================================
# SHOPPING LIST
# ============================================================

@mcp.tool()
def get_shopping_list() -> str:
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


@mcp.tool()
def add_to_shopping_list(product_id: int, amount: int = 1) -> str:
    """Add a product to the shopping list."""
    _post("/api/objects/shopping_list", {"product_id": product_id, "amount": amount})
    return f"Added product {product_id} (x{amount}) to shopping list"


@mcp.tool()
def add_note_to_shopping_list(note: str, amount: int = 1) -> str:
    """Add a free-text note to the shopping list (no product link needed)."""
    _post("/api/objects/shopping_list", {"note": note, "amount": amount})
    return f"Added note: {note}"


@mcp.tool()
def remove_from_shopping_list(shopping_list_item_id: int) -> str:
    """Remove an item from the shopping list by its shopping_list ID."""
    _delete(f"/api/objects/shopping_list/{shopping_list_item_id}")
    return f"Removed item {shopping_list_item_id} from shopping list"


@mcp.tool()
def clear_shopping_list() -> str:
    """Clear all items from the shopping list."""
    _post("/api/stock/shoppinglist/clear", {})
    return "Shopping list cleared"


@mcp.tool()
def add_missing_to_shopping_list(shopping_list_id: int = 1) -> str:
    """Add products below minimum stock amount to the shopping list."""
    _post(f"/api/stock/shoppinglist/add-missing-products", {"shopping_list_id": shopping_list_id})
    return "Added missing products to shopping list"


# ============================================================
# LOCATIONS
# ============================================================

@mcp.tool()
def list_locations() -> str:
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

@mcp.tool()
def list_product_groups() -> str:
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

@mcp.tool()
def list_quantity_units() -> str:
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

@mcp.tool()
def list_shopping_locations() -> str:
    """List all stores/shopping locations."""
    items = _get("/api/objects/shopping_location")
    if not items:
        return "No stores found."
    lines = []
    for s in items:
        lines.append(f"- {s.get('name', '?')} (id: {s.get('id', '?')})")
    return "\n".join(lines)


# ============================================================
# CHORES
# ============================================================

@mcp.tool()
def list_chores() -> str:
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

@mcp.tool()
def list_grocy_recipes() -> str:
    """List recipes stored in Grocy (basic — use Mealie MCP for full recipe management)."""
    items = _get("/api/objects/recipes")
    if not items:
        return "No recipes in Grocy."
    lines = []
    for r in items:
        lines.append(f"- {r.get('name', '?')} (id: {r.get('id', '?')})")
    return "\n".join(lines)


@mcp.tool()
def add_recipe_to_shopping_list(recipe_id: int, shopping_list_id: int = 1) -> str:
    """Add missing products from a Grocy recipe to the shopping list."""
    _post(f"/api/recipes/{recipe_id}/add-not-fulfilled-products-to-shoppinglist", {
        "shopping_list_id": shopping_list_id
    })
    return f"Added missing recipe {recipe_id} products to shopping list"


# ============================================================
# SYSTEM
# ============================================================

@mcp.tool()
def grocy_info() -> str:
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

if __name__ == "__main__":
    mcp.run(transport="stdio")
