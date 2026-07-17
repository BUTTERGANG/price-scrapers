"""Store config add/remove helpers and discovery endpoint plumbing."""
import json

import pytest

from utils import store_config


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "stores.json"
    path.write_text(json.dumps({
        "location": {"zip": "46220"},
        "stores": {
            "aldi": {
                "name": "Aldi",
                "locations": [{"store_id": "444-086", "address": "86th St"}],
            },
            "legacy": {"store_id": "old-1", "address": "Old Rd"},
        },
    }))
    monkeypatch.setattr(store_config, "STORES_PATH", path)
    return path


def test_add_location(cfg_file):
    entry = store_config.add_location("aldi", {"store_id": "444-088", "address": "82nd St"})
    assert [l["store_id"] for l in entry["locations"]] == ["444-086", "444-088"]
    on_disk = json.loads(cfg_file.read_text())
    assert len(on_disk["stores"]["aldi"]["locations"]) == 2


def test_add_duplicate_rejected(cfg_file):
    with pytest.raises(ValueError):
        store_config.add_location("aldi", {"store_id": "444-086"})


def test_add_migrates_legacy_entry(cfg_file):
    entry = store_config.add_location("legacy", {"store_id": "new-2"})
    ids = [l["store_id"] for l in entry["locations"]]
    assert ids == ["old-1", "new-2"]


def test_add_creates_new_retailer(cfg_file):
    store_config.add_location("target", {"store_id": "2391"}, name="Target")
    on_disk = json.loads(cfg_file.read_text())
    assert on_disk["stores"]["target"]["locations"][0]["store_id"] == "2391"


def test_remove_location(cfg_file):
    store_config.add_location("aldi", {"store_id": "444-088"})
    entry = store_config.remove_location("aldi", "444-086")
    assert [l["store_id"] for l in entry["locations"]] == ["444-088"]


def test_remove_missing_raises(cfg_file):
    with pytest.raises(ValueError):
        store_config.remove_location("aldi", "nope")
    with pytest.raises(KeyError):
        store_config.remove_location("nobody", "1")


def test_discover_endpoint_lists_retailers():
    from fastapi.testclient import TestClient
    from server import app

    with TestClient(app, raise_server_exceptions=False) as client:
        resp = client.get("/api/stores/discover")
        assert resp.status_code == 200
        assert "aldi" in resp.json()["discoverable"]

        resp = client.get("/api/stores/discover", params={"retailer": "aldi", "zip": "abc"})
        assert resp.status_code == 400

        resp = client.get("/api/stores/discover", params={"retailer": "walmart", "zip": "46220"})
        assert resp.status_code == 400  # no discoverer for walmart
