# grocy-mcp-server

A [Model Context Protocol](https://modelcontextprotocol.io) server for
[Grocy](https://grocy.info) — the self-hosted household ERP: stock, products,
shopping lists, chores, locations, stores and recipes.

Built for Grocy **4.x** (tested against 4.7.1). Read-only-capable: the tools are
annotated so MCP clients can tell reads from writes from destructive actions.

```
26 tools:  stock (8) · products (4) · shopping list (6) · locations (1)
           product groups (1) · quantity units (1) · stores (1) · chores (1)
           recipes (2) · system (1)
```

## Why this one

The most-used Grocy MCP servers are no longer maintained:

- `saya6k/mcp-grocy-api` — **archived**, README marked unmaintained
- `attmous/grocy-mcp` — last release April 2026; its
  [#10](https://github.com/attmous/grocy-mcp/issues/10) reports the
  `expiring_products` key removal on Grocy 4.x, unanswered

This server handles the Grocy 4.x `/api/stock/volatile` shape (a single object
keyed by category) rather than assuming a flat list, which is the failure mode
in the servers above.

## Install

### Docker

```bash
docker build -t grocy-mcp .
docker run --rm -i \
  -e GROCY_URL=https://grocy.example.com \
  -e GROCY_KEY=your-api-key \
  grocy-mcp
```

### From source

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
GROCY_URL=https://grocy.example.com GROCY_KEY=your-api-key python server.py
```

Requires Python 3.10+ (uses `dict | None` unions).

## Configuration

| Variable | Required | Description |
|---|---|---|
| `GROCY_URL` | yes | Base URL of your Grocy instance, no trailing slash needed |
| `GROCY_KEY` | yes | Grocy API key — Settings → Manage API keys → Add |

The key is sent as the `GROCY-API-KEY` header. Use a dedicated key so you can
revoke it without disturbing anything else.

## Client setup

**Claude Desktop / Cursor / any MCP client (stdio):**

```json
{
  "mcpServers": {
    "grocy": {
      "command": "python3",
      "args": ["/absolute/path/to/grocy-mcp-server/server.py"],
      "env": {
        "GROCY_URL": "https://grocy.example.com",
        "GROCY_KEY": "your-api-key"
      }
    }
  }
}
```

## Tools

### Stock
- `grocy_get_stock` — everything in stock with quantities, locations and due dates
- `grocy_get_stock_volatile` — overdue / due soon / expired / missing, grouped
- `grocy_get_product_stock` — stock detail for one product
- `grocy_add_stock` — add stock (amount, location, optional best-before)
- `grocy_consume_stock` — consume stock
- `grocy_transfer_stock` — move stock between locations
- `grocy_set_stock` — inventory correction (overwrites the count)
- `grocy_open_stock` — mark items as opened

### Products
- `grocy_list_products` — list or search by name
- `grocy_get_product` — full product record
- `grocy_create_product` — create a product
- `grocy_delete_product` — delete a product *(destructive)*

### Shopping list
- `grocy_get_shopping_list`
- `grocy_add_to_shopping_list`
- `grocy_add_note_to_shopping_list` — free text, no product needed
- `grocy_remove_from_shopping_list`
- `grocy_clear_shopping_list` *(destructive)*
- `grocy_add_missing_to_shopping_list` — everything below minimum stock

### Lookups
`grocy_list_locations`, `grocy_list_product_groups`,
`grocy_list_quantity_units`, `grocy_list_shopping_locations`,
`grocy_list_chores`, `grocy_list_grocy_recipes`, `grocy_get_system_info`

### Recipes
- `grocy_add_recipe_to_shopping_list` — add a recipe's missing ingredients

IDs are instance-specific. Every tool that takes an ID has a matching list tool;
resolve IDs at call time rather than hardcoding them.

## Notes and limitations

- Recipes are read-only and basic — Grocy's recipe API is thin. Use a dedicated
  recipe server if you need full recipe management.
- `grocy_set_stock` performs an inventory correction and overwrites the current
  amount. Prefer `grocy_add_stock` / `grocy_consume_stock` for normal changes.
- Tested against Grocy 4.7.1. Older 3.x instances may differ in the volatile
  stock response shape; both the 4.x object shape and a flat list are handled.

## License

MIT — see [LICENSE](LICENSE).
