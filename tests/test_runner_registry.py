"""Registry building from stores.json — declarative specs + multi-location."""
import json
from pathlib import Path

import pytest

from runner import _build_registry, available_retailers, expected_stores


@pytest.fixture
def stores():
    return json.loads(Path("config/stores.json").read_text())["stores"]


def test_real_config_produces_expected_keys(stores, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    keys = available_retailers(stores)
    assert "kroger_weekly_02100959" in keys
    assert "kroger_weekly_02100998" in keys
    assert "fresh_market_146th" in keys
    assert "fresh_market_rangeline" in keys
    for single in ("aldi", "meijer", "fresh_thyme", "target", "whole_foods",
                   "harvest_market", "gfs", "giant_eagle", "needlers"):
        assert single in keys
    # Vision circular registers when the API key is present
    assert "needlers_circular" in keys
    # Walmart re-enabled 2026-09-14 (real-browser CDP on residential IP); Costco still blocked
    assert "walmart" in keys
    assert "costco" not in keys


def test_needlers_circular_requires_env(stores, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    keys = available_retailers(stores)
    assert "needlers_circular" not in keys


def test_registry_entries_carry_store_ids(stores):
    registry = _build_registry(stores)
    assert registry["aldi"].store_id == "444-086"
    assert registry["fresh_market_146th"].store_id == "56"
    assert registry["kroger_weekly_02100959"].retailer == "kroger"


def test_multiple_locations_one_retailer():
    stores = {
        "aldi": {
            "name": "Aldi",
            "locations": [
                {"store_id": "444-086", "address": "86th St"},
                {"store_id": "444-088", "address": "82nd St"},
            ],
        }
    }
    keys = available_retailers(stores)
    assert keys == ["aldi_444-086", "aldi_444-088"]


def test_per_location_disable():
    stores = {
        "aldi": {
            "locations": [
                {"store_id": "444-086"},
                {"store_id": "444-088", "disabled": True},
            ],
        }
    }
    # One enabled location left → unsuffixed key
    assert available_retailers(stores) == ["aldi"]


def test_legacy_single_store_shape_still_works():
    stores = {"aldi": {"store_id": "444-086", "address": "1440 E. 86th St"}}
    registry = _build_registry(stores)
    assert "aldi" in registry
    assert registry["aldi"].store_id == "444-086"


def test_platform_entry_registers_without_spec():
    stores = {
        "some_iga": {
            "name": "Some IGA",
            "platform": "webstop",
            "locations": [
                {"store_id": "12", "webstop_retailer_id": "9999",
                 "webstop_host": "www.example.com"},
            ],
        }
    }
    assert available_retailers(stores) == ["some_iga"]


def test_unknown_platform_skipped():
    stores = {"mystery": {"platform": "nope", "locations": [{"store_id": "1"}]}}
    assert available_retailers(stores) == []


def test_expected_stores_includes_disabled(stores):
    expected = expected_stores(stores)
    by_key = {e["key"]: e for e in expected}
    # Walmart re-enabled 2026-09-14; Costco still blocked by bot detection
    assert by_key["walmart"]["disabled"] is False
    assert by_key["costco"]["disabled"] is True
    assert "bot detection" in (by_key["costco"]["disabled_reason"] or "").lower()
    assert by_key["aldi"]["disabled"] is False
    assert by_key["fresh_market_146th"]["store_id"] == "56"


# ---------------------------------------------------------------------------
# _run_one notification wiring — scraper failures and price alerts must
# reach utils.notify.notify (Telegram), not just the log.
# ---------------------------------------------------------------------------

@pytest.fixture
def patched_runner_db(db_conn, monkeypatch):
    """Route runner's pool access to the disposable test schema."""
    import runner
    monkeypatch.setattr(runner, "get_conn", lambda: db_conn)
    monkeypatch.setattr(runner, "release_conn", lambda c: None)
    return db_conn


def _entry(fn):
    from runner import RegistryEntry
    return RegistryEntry(key="kroger", retailer="kroger", store_id="01400441",
                         location={}, fn=fn)


def test_run_one_notifies_on_failure(patched_runner_db, monkeypatch):
    import runner
    sent = []
    monkeypatch.setattr(runner, "notify", sent.append)

    def _boom(items):
        raise RuntimeError("layout changed")

    assert runner._run_one(_entry(_boom), []) == []
    assert len(sent) == 1
    assert "Scraper failed: kroger" in sent[0]
    assert "layout changed" in sent[0]


def test_run_one_notifies_on_price_alert(patched_runner_db, monkeypatch, sample_price):
    import runner
    from utils.db import add_watchlist_item

    add_watchlist_item(patched_runner_db, sample_price["retailer"],
                       sample_price["product_id"], name=sample_price["name"],
                       target_price=sample_price["price"] + 1)
    sent = []
    monkeypatch.setattr(runner, "notify", sent.append)

    results = runner._run_one(_entry(lambda items: [dict(sample_price)]), [])
    assert len(results) == 1
    assert len(sent) == 1
    assert "Price alert" in sent[0]
    assert sample_price["name"] in sent[0]

    # Same price on the next run → alert deduplicated, nothing sent
    sent.clear()
    runner._run_one(_entry(lambda items: [dict(sample_price)]), [])
    assert sent == []
