"""Tests for server.py — auto-scrape scheduler anchoring.

Regression coverage for the "scraper running 30+ times a day" bug: uvicorn's
dev reloader re-runs the FastAPI lifespan on every backend file save, and the
scheduler must not treat each restart as a reason to fire again soon.
"""
from datetime import datetime, timedelta, timezone

import server
from utils.db import start_run


def _insert_run_at(conn, started_at):
    run_id = start_run(conn, "kroger", "01400441", 1)
    with conn.cursor() as cur:
        cur.execute("UPDATE runs SET started_at = %s WHERE id = %s", (started_at, run_id))
    conn.commit()


def test_no_prior_runs_falls_back_to_five_minutes(db_conn, monkeypatch):
    monkeypatch.setattr(server, "get_conn", lambda: db_conn)
    monkeypatch.setattr(server, "release_conn", lambda conn: None)

    now = datetime.now(timezone.utc)
    next_run = server._next_auto_scrape_time()
    assert now + timedelta(minutes=4) <= next_run <= now + timedelta(minutes=6)


def test_anchors_to_last_run_plus_six_hours(db_conn, monkeypatch):
    monkeypatch.setattr(server, "get_conn", lambda: db_conn)
    monkeypatch.setattr(server, "release_conn", lambda conn: None)

    last_run = datetime.now(timezone.utc) - timedelta(hours=2)
    _insert_run_at(db_conn, last_run)

    next_run = server._next_auto_scrape_time()
    expected = last_run + timedelta(hours=6)
    assert abs((next_run - expected).total_seconds()) < 1


def test_overdue_run_falls_back_to_five_minutes_not_the_past(db_conn, monkeypatch):
    monkeypatch.setattr(server, "get_conn", lambda: db_conn)
    monkeypatch.setattr(server, "release_conn", lambda conn: None)

    last_run = datetime.now(timezone.utc) - timedelta(hours=10)
    _insert_run_at(db_conn, last_run)

    now = datetime.now(timezone.utc)
    next_run = server._next_auto_scrape_time()
    assert now <= next_run <= now + timedelta(minutes=6)


def test_repeated_calls_after_same_last_run_are_stable(db_conn, monkeypatch):
    """Simulates repeated dev-reload restarts: recomputing the anchor after
    the same last run must not keep pushing the schedule out."""
    monkeypatch.setattr(server, "get_conn", lambda: db_conn)
    monkeypatch.setattr(server, "release_conn", lambda conn: None)

    last_run = datetime.now(timezone.utc) - timedelta(hours=1)
    _insert_run_at(db_conn, last_run)

    first = server._next_auto_scrape_time()
    second = server._next_auto_scrape_time()
    assert first == second
