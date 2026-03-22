"""Telegram bot interface for Grocery Price Scrapers.

Commands:
    /start                       — welcome message and command list
    /stores                      — list available retailer keys + last run time
    /scrape [store1 store2 ...]  — trigger a scrape in the background
    /price  <item>               — cheapest price per retailer (last 7 days)
    /deals  [min_pct]            — active sales (default: 10% off)
    /compare <item>              — unit price comparison ($/oz, $/fl_oz, $/lb, $/ct)
    /ask    <question>           — natural language query via Claude AI

Plain-text messages are treated as /ask queries when ANTHROPIC_API_KEY is set.

Required environment variables (in .env):
    TELEGRAM_BOT_TOKEN   — from @BotFather
    ANTHROPIC_API_KEY    — optional; enables /ask command
"""
import asyncio
import json
import logging
import os
import threading
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

STORES = json.loads(Path("config/stores.json").read_text())
ITEMS = json.loads(Path("config/items.json").read_text())

_UNIT_LABELS = {
    "per_fl_oz": "per fl oz",
    "per_oz":    "per oz",
    "per_lb":    "per lb",
    "per_ct":    "per ct",
}

# Track in-flight scrapes — prevent duplicate concurrent runs per retailer
_active_scrapes: set[str] = set()
_scrape_lock = threading.Lock()

# ---------------------------------------------------------------------------
# DB helpers — each creates its own connection (thread-safe)
# ---------------------------------------------------------------------------

def _current_prices(item: str, retailer: Optional[str] = None) -> list[dict]:
    from utils import get_conn, cheapest_per_retailer
    conn = get_conn()
    try:
        rows = cheapest_per_retailer(conn, item)
        if retailer:
            rows = [r for r in rows if r.get("retailer") == retailer]
        return rows
    finally:
        conn.close()


def _active_deals(min_pct: float = 10.0, retailer: Optional[str] = None) -> list[dict]:
    from utils import get_conn, find_active_deals
    conn = get_conn()
    try:
        deals = find_active_deals(conn, min_pct)
        if retailer:
            deals = [d for d in deals if d.get("retailer") == retailer]
        return deals
    finally:
        conn.close()


def _unit_price_rows(item: str) -> list[dict]:
    """Query DB for recent records with a normalized unit price for the given item."""
    from utils import get_conn
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT p.*
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices
                WHERE LOWER(name) LIKE ?
                GROUP BY retailer, product_id
            ) latest_only
                ON p.retailer = latest_only.retailer
               AND p.product_id = latest_only.product_id
               AND p.scraped_at = latest_only.latest
            WHERE LOWER(p.name) LIKE ?
              AND p.unit_price_normalized IS NOT NULL
              AND p.scraped_at >= datetime('now', '-7 days')
            ORDER BY p.unit_canonical, p.unit_price_normalized
            LIMIT 30
            """,
            (f"%{item.lower()}%", f"%{item.lower()}%"),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _weekly_specials(category_hint: Optional[str] = None) -> list[dict]:
    """Recent items sorted by effective price — sales first, then by unit price.

    Gives Claude a broad view of what's currently available and cheap, which
    is the foundation for budget planning and recipe suggestions.
    Parses extra_json so deal_text/sale_story are accessible at the top level.
    """
    from utils import get_conn
    conn = get_conn()
    try:
        params: list = []
        category_filter = ""
        if category_hint:
            category_filter = "AND LOWER(p.name) LIKE ?"
            params.append(f"%{category_hint.lower()}%")

        rows = conn.execute(
            f"""
            SELECT p.name, p.retailer, p.price, p.sale_price,
                   p.unit, p.unit_price_normalized, p.unit_canonical, p.extra_json
            FROM prices p
            INNER JOIN (
                SELECT retailer, product_id, MAX(scraped_at) AS latest
                FROM prices
                WHERE scraped_at >= datetime('now', '-7 days')
                GROUP BY retailer, product_id
            ) latest_only
                ON p.retailer = latest_only.retailer
               AND p.product_id = latest_only.product_id
               AND p.scraped_at = latest_only.latest
            WHERE p.scraped_at >= datetime('now', '-7 days')
              AND COALESCE(p.sale_price, p.price, 0) > 0
              {category_filter}
            ORDER BY
                CASE WHEN p.sale_price IS NOT NULL THEN 0 ELSE 1 END,
                COALESCE(p.sale_price, p.price) ASC
            LIMIT 80
            """,
            params,
        ).fetchall()

        results = []
        for row in rows:
            r = dict(row)
            # Lift deal_text/sale_story out of extra_json for Claude to see
            if r.get("extra_json"):
                try:
                    extra = json.loads(r["extra_json"])
                    r["deal_text"] = extra.get("deal_text") or extra.get("sale_story")
                except Exception:
                    pass
            del r["extra_json"]
            results.append(r)
        return results
    finally:
        conn.close()


def _last_run_times() -> dict[str, Optional[str]]:
    """Return {retailer: finished_at} for the last successful run of each retailer."""
    from runner import available_retailers
    from utils import get_conn, last_successful_run
    conn = get_conn()
    try:
        retailers = available_retailers(STORES["stores"])
        return {
            r: (last_successful_run(conn, r) or {}).get("finished_at")
            for r in retailers
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Message formatters
# ---------------------------------------------------------------------------

def _fmt_prices(rows: list[dict], item: str) -> str:
    if not rows:
        return f"No recent prices found for *{item}*\\. Run /scrape first\\."
    lines = [f"*Prices for '{item}':*"]
    for r in rows:
        effective = r.get("sale_price") or r.get("price") or 0.0
        tag = " 🏷 SALE" if r.get("sale_price") else ""
        unit = f" \\({r['unit']}\\)" if r.get("unit") else ""
        lines.append(f"  • `{r['retailer']:20s}` ${effective:.2f}{unit}{tag}")
    return "\n".join(lines)


def _fmt_deals(deals: list[dict]) -> str:
    if not deals:
        return "No active deals found\\. Run /scrape to refresh\\."
    lines = ["*Current deals:*"]
    for d in deals[:15]:
        pct = round(d.get("savings_pct", 0))
        name = d["name"][:40]
        lines.append(
            f"  • `{d['retailer']:16s}` "
            f"${d['sale_price']:.2f} \\(was ${d['price']:.2f}, \\-{pct}%\\)  {name}"
        )
    return "\n".join(lines)


def _fmt_unit_prices(rows: list[dict], item: str) -> str:
    if not rows:
        return (
            f"No unit price data for *{item}*\\. "
            "Run /scrape first, or try a broader search term\\."
        )
    lines = [f"*Unit price comparison: '{item}'*"]
    current_canon = None
    for r in rows:
        canon = r.get("unit_canonical")
        if canon != current_canon:
            current_canon = canon
            label = _UNIT_LABELS.get(canon, canon or "unknown")
            lines.append(f"\n  _\\[{label}\\]_")
        norm = r.get("unit_price_normalized") or 0.0
        if norm < 0.10:
            up_str = f"${norm:.4f}/{_UNIT_LABELS.get(canon,'unit')}"
        else:
            up_str = f"${norm:.2f}/{_UNIT_LABELS.get(canon,'unit')}"
        effective = r.get("sale_price") or r.get("price") or 0.0
        sale_tag = " 🏷" if r.get("sale_price") else ""
        name = r["name"][:38]
        lines.append(
            f"  • `{r['retailer']:16s}` {up_str:16s} \\(${effective:.2f}\\){sale_tag}  {name}"
        )
    return "\n".join(lines)


def _fmt_stores(run_times: dict[str, Optional[str]], active: set[str]) -> str:
    lines = ["*Available stores:*"]
    for retailer, ts in sorted(run_times.items()):
        if retailer in active:
            status = " ⏳ _scraping now_"
        elif ts:
            # Show just the date portion (first 10 chars of ISO timestamp)
            status = f" _\\(last: {ts[:10]}\\)_"
        else:
            status = " _\\(never run\\)_"
        lines.append(f"  • `{retailer}`{status}")
    return "\n".join(lines)


def _fmt_specials(rows: list[dict], category_hint: Optional[str] = None) -> str:
    """Compact plain-text listing for Claude to reason about (not shown to user)."""
    if not rows:
        return "No items found in the last 7 days. Suggest running /scrape first."

    header = f"Items matching '{category_hint}':" if category_hint else "Current weekly items (sales first):"
    lines = [header]

    for r in rows:
        effective = r.get("sale_price") or r.get("price") or 0.0
        sale_tag = " [SALE]" if r.get("sale_price") else ""
        unit = f" {r['unit']}" if r.get("unit") else ""

        # unit price string
        up_str = ""
        norm = r.get("unit_price_normalized")
        canon = r.get("unit_canonical")
        if norm and canon:
            label = _UNIT_LABELS.get(canon, canon)
            up_str = f" [${norm:.4f}/{label}]" if norm < 0.10 else f" [${norm:.2f}/{label}]"

        # deal text (BOGO, % off, etc.)
        deal = r.get("deal_text") or ""
        deal_str = f" ({deal})" if deal else ""

        lines.append(
            f"  {r['retailer']:16s} ${effective:.2f}{unit}{up_str}{sale_tag}{deal_str}  {r['name'][:52]}"
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Claude tool definitions for /ask
# ---------------------------------------------------------------------------

_ASK_TOOLS = [
    {
        "name": "search_prices",
        "description": (
            "Search for current grocery prices by item name. Returns the cheapest "
            "price per retailer from the last 7 days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "Item to search for, e.g. 'milk', 'chicken breast', 'eggs 12ct'",
                },
                "retailer": {
                    "type": "string",
                    "description": "Optional: limit to one retailer (e.g. 'kroger', 'aldi')",
                },
            },
            "required": ["item"],
        },
    },
    {
        "name": "get_deals",
        "description": (
            "Get items currently on sale. Returns items where sale_price < regular price, "
            "sorted by savings percentage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_savings_pct": {
                    "type": "number",
                    "description": "Minimum savings percentage to include (default 10)",
                },
                "retailer": {
                    "type": "string",
                    "description": "Optional: limit to one retailer",
                },
            },
        },
    },
    {
        "name": "compare_unit_prices",
        "description": (
            "Compare items by standardized unit price ($/fl_oz, $/oz, $/lb, or $/ct). "
            "Essential for comparing different package sizes — e.g. a 1-gal milk vs "
            "a half-gallon, or a 10-oz bag vs a 16-oz bag."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "description": "Item to compare, e.g. 'milk', 'orange juice', 'chicken breast'",
                },
            },
            "required": ["item"],
        },
    },
    {
        "name": "get_weekly_specials",
        "description": (
            "Get all items currently available from recent scrapes, sorted by price "
            "(sales first, then cheapest). Returns up to 80 items with unit prices "
            "when available. "
            "Use this for: budget planning ('I have $X for groceries'), "
            "recipe suggestions ('what can I make with what's on sale?'), "
            "and finding cheap ingredients for a specific dish. "
            "Optionally filter by category keyword."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "category_hint": {
                    "type": "string",
                    "description": (
                        "Optional keyword to narrow results, e.g. 'chicken', "
                        "'produce', 'dairy', 'beef', 'pasta'. Omit to get a broad "
                        "view of all available items."
                    ),
                },
            },
        },
    },
]

_ASK_SYSTEM = """You are a helpful grocery price assistant with access to live price data \
from 13 stores near Indianapolis. Answer questions about prices, deals, budget shopping, \
and recipes based on what's currently cheap or on sale.

PRICE & DEALS questions: use search_prices or get_deals.

BUDGET questions ("I have $X", "what can I buy for $X", "cheapest way to feed N people"):
1. Call get_weekly_specials() to see what's available and cheap this week.
2. Optionally call it again with a category_hint (e.g. "chicken", "produce") for more detail.
3. Build a realistic grocery basket that fits the budget — include protein, produce, dairy, \
staples. Use unit prices to pick the best value option when sizes differ.
4. List each item with its price and which store carries it.
5. Suggest 1–2 simple recipes using the cheap ingredients you identified.
6. Give a total estimated cost.

RECIPE questions ("what can I make with X?", "recipes using sale items", \
"dinner ideas for $20"):
1. Call get_weekly_specials() to see cheap/sale ingredients available this week.
2. Suggest 2–3 recipes that use those ingredients plus common pantry staples.
3. For each recipe, mention the key sale/cheap ingredients and their prices.
4. Give an estimated per-serving cost.

UNIT PRICE questions: use compare_unit_prices.

BOGO / % off deals with no listed dollar price: mention the deal exists \
but note that no exact price is available — the user should check in-store.

Format: be concise, use bullet points, show dollar amounts clearly. \
No markdown headers. Keep answers under 600 words."""


async def _run_ask(question: str) -> str:
    """Run a Claude tool-use conversation to answer a price question."""
    import anthropic

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": question}]
    loop = asyncio.get_event_loop()

    for _ in range(6):  # max tool-call rounds
        response = await loop.run_in_executor(
            None,
            lambda: client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1200,
                tools=_ASK_TOOLS,
                messages=messages,
                system=_ASK_SYSTEM,
            ),
        )

        if response.stop_reason == "end_turn":
            return "\n".join(
                block.text
                for block in response.content
                if hasattr(block, "text")
            ).strip()

        if response.stop_reason != "tool_use":
            break

        # Execute each tool call and collect results
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            inp = block.input
            tool_name = block.name

            if tool_name == "search_prices":
                raw = await loop.run_in_executor(
                    None, lambda i=inp: _current_prices(i["item"], i.get("retailer"))
                )
                result = _fmt_prices(raw, inp["item"])

            elif tool_name == "get_deals":
                raw = await loop.run_in_executor(
                    None,
                    lambda i=inp: _active_deals(
                        i.get("min_savings_pct", 10.0), i.get("retailer")
                    ),
                )
                result = _fmt_deals(raw)

            elif tool_name == "compare_unit_prices":
                raw = await loop.run_in_executor(
                    None, lambda i=inp: _unit_price_rows(i["item"])
                )
                result = _fmt_unit_prices(raw, inp["item"])

            elif tool_name == "get_weekly_specials":
                hint = inp.get("category_hint")
                raw = await loop.run_in_executor(
                    None, lambda h=hint: _weekly_specials(h)
                )
                result = _fmt_specials(raw, hint)

            else:
                result = f"Unknown tool: {tool_name}"

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    return "Sorry, I wasn't able to answer that. Try /price or /deals directly."


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
    ask_line = (
        "  /ask `<question>` — ask anything in plain English\n"
        "  _(or just type a question — no slash needed)_\n"
        if has_claude
        else "  /ask — requires ANTHROPIC\\_API\\_KEY in .env\n"
    )
    await update.message.reply_text(
        "*Grocery Price Bot* 🛒\n\n"
        "*Commands:*\n"
        "  /stores — list stores \\+ last run time\n"
        "  /scrape `[store1 store2 ...]` — run scraper\\(s\\) in background\n"
        "  /price `<item>` — cheapest price across stores\n"
        "  /deals `[min%]` — active deals \\(default: 10% off\\)\n"
        "  /compare `<item>` — unit price comparison\n"
        + ask_line,
        parse_mode="MarkdownV2",
    )


async def cmd_stores(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    loop = asyncio.get_event_loop()
    run_times = await loop.run_in_executor(None, _last_run_times)
    with _scrape_lock:
        active = set(_active_scrapes)
    await update.message.reply_text(
        _fmt_stores(run_times, active), parse_mode="MarkdownV2"
    )


async def cmd_scrape(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from runner import available_retailers, run_retailers

    loop = asyncio.get_event_loop()
    all_retailers = await loop.run_in_executor(
        None, lambda: available_retailers(STORES["stores"])
    )

    requested = [a.lower() for a in (context.args or [])]
    targets = requested if requested else all_retailers

    unknown = [t for t in targets if t not in all_retailers]
    if unknown:
        await update.message.reply_text(
            f"Unknown store\\(s\\): `{'`, `'.join(unknown)}`\nUse /stores to see valid names\\.",
            parse_mode="MarkdownV2",
        )
        return

    with _scrape_lock:
        already = [t for t in targets if t in _active_scrapes]
        to_start = [t for t in targets if t not in _active_scrapes]
        _active_scrapes.update(to_start)

    if already:
        await update.message.reply_text(
            f"Already scraping: `{'`, `'.join(already)}`", parse_mode="MarkdownV2"
        )
    if not to_start:
        return

    store_list = "`, `".join(to_start)
    await update.message.reply_text(
        f"⏳ Starting `{store_list}` — I'll message you when done\\.",
        parse_mode="MarkdownV2",
    )

    async def _run_scrape():
        conn = None
        try:
            from utils import get_conn
            conn = get_conn()
            workers = min(4, len(to_start))
            results = await loop.run_in_executor(
                None,
                lambda: run_retailers(
                    to_start, STORES["stores"], ITEMS["queries"], conn,
                    workers=workers,
                ),
            )
            await update.message.reply_text(
                f"✅ Done — {len(results)} item\\(s\\) scraped from {len(to_start)} store\\(s\\)\\.",
                parse_mode="MarkdownV2",
            )
        except Exception as exc:
            logger.exception("Scrape task failed")
            await update.message.reply_text(f"❌ Scrape failed: {exc}")
        finally:
            with _scrape_lock:
                _active_scrapes.difference_update(to_start)
            if conn:
                conn.close()

    asyncio.create_task(_run_scrape())


async def cmd_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /price `<item>`  e\\.g\\. /price milk",
            parse_mode="MarkdownV2",
        )
        return
    item = " ".join(context.args)
    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, lambda: _current_prices(item))
    await update.message.reply_text(_fmt_prices(rows, item), parse_mode="MarkdownV2")


async def cmd_deals(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        min_pct = float(context.args[0]) if context.args else 10.0
    except ValueError:
        min_pct = 10.0
    loop = asyncio.get_event_loop()
    deals = await loop.run_in_executor(None, lambda: _active_deals(min_pct))
    await update.message.reply_text(_fmt_deals(deals), parse_mode="MarkdownV2")


async def cmd_compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /compare `<item>`  e\\.g\\. /compare milk",
            parse_mode="MarkdownV2",
        )
        return
    item = " ".join(context.args)
    loop = asyncio.get_event_loop()
    rows = await loop.run_in_executor(None, lambda: _unit_price_rows(item))
    await update.message.reply_text(
        _fmt_unit_prices(rows, item), parse_mode="MarkdownV2"
    )


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        await update.message.reply_text(
            "The /ask command requires `ANTHROPIC_API_KEY` in your \\.env file\\.",
            parse_mode="MarkdownV2",
        )
        return
    question = " ".join(context.args) if context.args else ""
    if not question:
        await update.message.reply_text(
            "Usage: /ask `<question>`  e\\.g\\. /ask what's the cheapest milk?",
            parse_mode="MarkdownV2",
        )
        return
    await update.message.reply_text("🤔 Looking that up\\.\\.\\.", parse_mode="MarkdownV2")
    try:
        answer = await _run_ask(question)
        # Telegram message limit is 4096 chars
        if len(answer) > 4000:
            answer = answer[:4000] + "…"
        await update.message.reply_text(answer)
    except Exception as exc:
        logger.exception("Ask command failed")
        await update.message.reply_text(f"❌ Error: {exc}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Route plain-text messages to /ask if ANTHROPIC_API_KEY is set."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        await update.message.reply_text(
            "Use /help or /start to see available commands\\.",
            parse_mode="MarkdownV2",
        )
        return
    text = (update.message.text or "").strip()
    if not text:
        return
    await update.message.reply_text("🤔 Looking that up\\.\\.\\.", parse_mode="MarkdownV2")
    try:
        answer = await _run_ask(text)
        if len(answer) > 4000:
            answer = answer[:4000] + "…"
        await update.message.reply_text(answer)
    except Exception as exc:
        logger.exception("Message handler failed")
        await update.message.reply_text(f"❌ Error: {exc}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_start))
    app.add_handler(CommandHandler("stores",  cmd_stores))
    app.add_handler(CommandHandler("scrape",  cmd_scrape))
    app.add_handler(CommandHandler("price",   cmd_price))
    app.add_handler(CommandHandler("deals",   cmd_deals))
    app.add_handler(CommandHandler("compare", cmd_compare))
    app.add_handler(CommandHandler("ask",     cmd_ask))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    has_claude = bool(os.getenv("ANTHROPIC_API_KEY"))
    logger.info(
        f"Bot starting. Claude /ask: {'enabled' if has_claude else 'disabled (no ANTHROPIC_API_KEY)'}."
    )
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
