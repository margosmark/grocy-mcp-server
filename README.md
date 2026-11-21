# grocy-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server that connects any MCP client — Claude Desktop, Cursor, or anything else — to a self-hosted [Grocy](https://grocy.info) instance (self-hosted groceries & household management).

**26 tools**, all prefixed `grocy_`, covering:

- **Stock** — full stock view, volatile (due soon / overdue / missing), per-product detail, add / consume / transfer / set / open
- **Products** — list & search, read, create, delete
- **Shopping list** — read, add product or free-text note, remove, clear, auto-add missing & recipe ingredients
- **Household data** — storage locations, product groups, quantity units, stores, chores
- **Extras** — Grocy's own recipes (basic; for full recipe management pair with `mealie-mcp-server`) and system info

Every tool carries [MCP tool annotations](https://modelcontextprotocol.io/specification/2025-06-18/server/tools#tool-annotations) (`readOnly` / `write` / `destructive` / `overwrite`) so clients can warn you before anything destructive runs.

## Grocy compatibility

Verified against **Grocy 4.7.1** — both a long-running instance and a fresh container — including every read and write tool. That covers the Grocy 4.x `/api/stock/volatile` response change: 4.x returns `due_products` / `overdue_products` buckets instead of `expiring_products`, the rename that silently breaks other Grocy MCP servers (e.g. [attmous/grocy-mcp#10](https://github.com/attmous/grocy-mcp/issues/10)). This server reads the 4.x keys and falls back to the Grocy 3.x names, and handles the other 4.x field renames (`stock_amount`, `next_due_date`, `created_object_id`, shopping-list rows without an embedded `product_name`).

## Requirements

- Python **3.10+** (or Docker)
- A running Grocy instance and an API key
  (Grocy admin → **Manage API keys**)

## Environment variables

| Variable | Required | Example value |
|---|---|---|
| `GROCY_URL` | ✅ | `https://grocy.example.com` |
| `GROCY_KEY` | ✅ | `<your-grocy-api-key>` |

Placeholders only — never commit real values. The server reads them from its environment at startup.

## Install

### pip

```bash
git clone https://github.com/margosmark/grocy-mcp-server.git
cd grocy-mcp-server
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### Docker

```bash
git clone https://github.com/margosmark/grocy-mcp-server.git
cd grocy-mcp-server
docker build -t grocy-mcp .
```

> The server speaks MCP over **stdio** — you don't run it by hand; your MCP client starts it (locally or via `docker run -i --rm`, see below).

## Client configuration

### Claude Desktop

Add to `claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`,
Windows: `%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "grocy": {
      "command": "python",
      "args": ["/absolute/path/to/grocy-mcp-server/server.py"],
      "env": {
        "GROCY_URL": "https://grocy.example.com",
        "GROCY_KEY": "<your-grocy-api-key>"
      }
    }
  }
}
```

Using Docker instead of a local Python environment:

```json
{
  "mcpServers": {
    "grocy": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-e", "GROCY_URL",
        "-e", "GROCY_KEY",
        "grocy-mcp"
      ],
      "env": {
        "GROCY_URL": "https://grocy.example.com",
        "GROCY_KEY": "<your-grocy-api-key>"
      }
    }
  }
}
```

(`-e NAME` with no value forwards the entry from the client's `env` block into the container.)

### Cursor

Create `.cursor/mcp.json` in your project (or `~/.cursor/mcp.json` for global) with the **same JSON as above**:

```json
{
  "mcpServers": {
    "grocy": {
      "command": "python",
      "args": ["/absolute/path/to/grocy-mcp-server/server.py"],
      "env": {
        "GROCY_URL": "https://grocy.example.com",
        "GROCY_KEY": "<your-grocy-api-key>"
      }
    }
  }
}
```

Restart the client after editing; the `grocy_*` tools appear in the tool picker.

## Sample session

Captured live from this server over MCP stdio against a fresh **Grocy 4.7.1** container:

```text
# connected — tools/list
(26 tools) grocy_get_stock, grocy_get_stock_volatile, grocy_get_product_stock, grocy_add_stock, grocy_consume_stock, grocy_transfer_stock, grocy_set_stock, grocy_open_stock, grocy_list_products, grocy_get_product, grocy_create_product, grocy_delete_product, grocy_get_shopping_list, grocy_add_to_shopping_list, grocy_add_note_to_shopping_list, grocy_remove_from_shopping_list, grocy_clear_shopping_list, grocy_add_missing_to_shopping_list, grocy_list_locations, grocy_list_product_groups, grocy_list_quantity_units, grocy_list_shopping_locations, grocy_list_chores, grocy_list_grocy_recipes, grocy_add_recipe_to_shopping_list, grocy_get_system_info

> grocy_get_stock_volatile()
## Due Soon

- **Whole Milk**: 2 — best before 2026-11-25

## Overdue (best before date passed)

- **Probe Butter**: 9 — best before 2026-01-05

> grocy_get_stock()
## Current Stock

- **Probe Butter**: 9 @ Fridge [4 opened] (due: 2026-01-05)
- **Whole Milk**: 2 @ Fridge (due: 2026-11-25)

> grocy_get_system_info()
## Grocy System Info
- **grocy_version**: v4.7.1 (released 2026-09-04)
- **php_version**: 8.5.13
- **sqlite_version**: 3.53.4

> grocy_add_to_shopping_list(product_id=6, amount=2)
Added product 6 (x2) to shopping list

> grocy_get_shopping_list()
## Shopping List

⬜ 2x Whole Milk (id: 8)
⬜ 1x sourdough starter (id: 9)

```

## Tools (26)

| Tool | Description | Type |
|---|---|---|
| `grocy_get_stock` | Get all products currently in stock with quantities and next due dates. | 🟢 read |
| `grocy_get_stock_volatile` | Get products that are due soon, overdue, expired, or currently missing. | 🟢 read |
| `grocy_get_product_stock` | Get stock details for a specific product. | 🟢 read |
| `grocy_add_stock` | Add stock for a product. Use grocy_list_locations to get valid location_id values. | 🟡 write |
| `grocy_consume_stock` | Consume (remove) stock for a product. This permanently reduces stock. | 🔴 destructive |
| `grocy_transfer_stock` | Transfer stock between locations. Use grocy_list_locations to get valid IDs. | 🟡 write |
| `grocy_set_stock` | Set stock to a specific amount (inventory adjustment). Overwrites the current count. | 🟠 overwrite |
| `grocy_open_stock` | Mark stock as opened. | 🟡 write |
| `grocy_list_products` | List products. Optional search by name. | 🟢 read |
| `grocy_get_product` | Get full product details by ID. | 🟢 read |
| `grocy_create_product` | Create a new product. Defaults to your first storage location and quantity unit when not given. Use grocy_list_product_groups / grocy_list_locations / grocy_list_quantity_units for valid IDs. | 🟡 write |
| `grocy_delete_product` | Delete a product by ID. This cannot be undone. | 🔴 destructive |
| `grocy_get_shopping_list` | Get all items on the shopping list. | 🟢 read |
| `grocy_add_to_shopping_list` | Add a product to the shopping list. | 🟡 write |
| `grocy_add_note_to_shopping_list` | Add a free-text note to the shopping list (no product link needed). | 🟡 write |
| `grocy_remove_from_shopping_list` | Remove an item from the shopping list by its shopping_list ID. | 🔴 destructive |
| `grocy_clear_shopping_list` | Clear all items from the shopping list. This cannot be undone. | 🔴 destructive |
| `grocy_add_missing_to_shopping_list` | Add products below minimum stock amount to the shopping list. | 🟡 write |
| `grocy_list_locations` | List all storage locations. | 🟢 read |
| `grocy_list_product_groups` | List all product groups/categories. | 🟢 read |
| `grocy_list_quantity_units` | List all quantity units. | 🟢 read |
| `grocy_list_shopping_locations` | List all stores/shopping locations. | 🟢 read |
| `grocy_list_chores` | List all household chores. | 🟢 read |
| `grocy_list_grocy_recipes` | List recipes stored in Grocy (basic — use the mealie MCP server for full recipe management). | 🟢 read |
| `grocy_add_recipe_to_shopping_list` | Add missing products from a Grocy recipe to the shopping list. | 🟡 write |
| `grocy_get_system_info` | Get Grocy system info (version, etc.). | 🟢 read |

## Development

```bash
pip install -r requirements.txt -r requirements-dev.txt
ruff check .   # lint
pytest         # tests — Grocy is faked in-process, no network or instance needed
```

CI (`.github/workflows/ci.yml`) runs the same two commands on every push. The tests pin the Grocy 4.x response shapes (volatile buckets, `stock_amount`, `created_object_id`, shopping-list name resolution) and the Grocy 3.x fallbacks, and fail if the tool list and this README drift apart.

## License

[MIT](LICENSE) © Mark Arslan
