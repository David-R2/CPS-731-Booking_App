"""Team 16 quota tests: original tests by Sean; supplementary tests drafted for Jaden."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from booking.database import initialize
from booking.main import create_app


def test_quota_counts_occurrences_and_releases_capacity(tmp_path: Path) -> None:
    database = tmp_path / "quota.sqlite3"
    initialize(database)
    now = datetime(2030, 1, 1)
    clock = [now]
    with TestClient(create_app(database, clock=lambda: clock[0], quota_limit=3)) as api:
        owner = {"X-User-ID": "1"}
        other = {"X-User-ID": "2"}
        start = now + timedelta(days=1)

        def body(day: int, resource: int = 1) -> dict[str, object]:
            at = start + timedelta(days=day)
            return {
                "resource_id": resource,
                "start": at.isoformat(),
                "end": (at + timedelta(hours=1)).isoformat(),
            }

        first = api.post("/bookings", headers=owner, json=body(0))
        assert first.status_code == 201
        series = api.post(
            "/booking-series", headers=owner, json={**body(1, 2), "count": 2}
        )
        assert series.status_code == 201
        before = api.get("/bookings").json()
        rejected = api.post(
            "/booking-series", headers=owner, json={**body(2), "count": 1}
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "Booking quota exceeded"
        assert api.get("/bookings").json() == before
        assert api.post("/bookings", headers=other, json=body(2)).status_code == 201
        conflict = api.post("/bookings", headers=owner, json=body(2))
        assert (
            conflict.json()["detail"] == "Resource is already booked for this interval"
        )
        assert (
            api.post(
                f"/bookings/{first.json()['id']}/cancel", headers=owner
            ).status_code
            == 200
        )
        assert api.post("/bookings", headers=owner, json=body(3)).status_code == 201
        clock[0] = start + timedelta(days=1)
        assert api.post("/bookings", headers=owner, json=body(4)).status_code == 201


def test_quota_configuration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BOOKING_QUOTA_LIMIT", "2")
    database = tmp_path / "quota.sqlite3"
    initialize(database)
    with TestClient(create_app(database, clock=lambda: datetime(2030, 1, 1))) as api:
        payload = {
            "resource_id": 1,
            "start": "2030-01-02T10:00:00",
            "end": "2030-01-02T11:00:00",
            "count": 3,
        }
        response = api.post("/booking-series", headers={"X-User-ID": "1"}, json=payload)
        assert response.status_code == 409
        assert api.get("/bookings").json() == []
    with pytest.raises(ValueError):
        create_app(database, quota_limit=0)


def test_series_fits_exactly_or_is_rejected_atomically(tmp_path: Path) -> None:
    database = tmp_path / "quota.sqlite3"
    initialize(database)
    with TestClient(create_app(database, clock=lambda: datetime(2030, 1, 1))) as api:
        headers = {"X-User-ID": "1"}
        first = {
            "resource_id": 1,
            "start": "2030-01-02T10:00:00",
            "end": "2030-01-02T11:00:00",
            "count": 10,
        }
        assert (
            api.post("/booking-series", headers=headers, json=first).status_code == 201
        )
        before = api.get("/bookings").json()
