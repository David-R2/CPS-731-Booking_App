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


# Original quota tests by Sean


def test_quota_counts_occurrences_and_releases_capacity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "quota.sqlite3"
    initialize(database)
    now = datetime(2030, 1, 1)
    clock = [now]

    with TestClient(
        create_app(database, clock=lambda: clock[0], quota_limit=3)
    ) as api:
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
            "/booking-series",
            headers=owner,
            json={**body(1, 2), "count": 2},
        )
        assert series.status_code == 201

        before = api.get("/bookings").json()

        rejected = api.post(
            "/booking-series",
            headers=owner,
            json={**body(2), "count": 1},
        )

        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "Booking quota exceeded"
        assert api.get("/bookings").json() == before

        assert api.post(
            "/bookings", headers=other, json=body(2)
        ).status_code == 201

        conflict = api.post(
            "/bookings", headers=owner, json=body(2)
        )

        assert (
            conflict.json()["detail"]
            == "Resource is already booked for this interval"
        )

        assert (
            api.post(
                f"/bookings/{first.json()['id']}/cancel",
                headers=owner,
            ).status_code
            == 200
        )

        assert api.post(
            "/bookings", headers=owner, json=body(3)
        ).status_code == 201

        clock[0] = start + timedelta(days=1)

        assert api.post(
            "/bookings", headers=owner, json=body(4)
        ).status_code == 201


def test_quota_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOKING_QUOTA_LIMIT", "2")

    database = tmp_path / "quota.sqlite3"
    initialize(database)

    with TestClient(
        create_app(database, clock=lambda: datetime(2030, 1, 1))
    ) as api:
        payload = {
            "resource_id": 1,
            "start": "2030-01-02T10:00:00",
            "end": "2030-01-02T11:00:00",
            "count": 3,
        }

        response = api.post(
            "/booking-series",
            headers={"X-User-ID": "1"},
            json=payload,
        )

        assert response.status_code == 409
        assert api.get("/bookings").json() == []

    with pytest.raises(ValueError):
        create_app(database, quota_limit=0)


def test_series_fits_exactly_or_is_rejected_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOKING_QUOTA_LIMIT", raising=False)

    database = tmp_path / "quota.sqlite3"
    initialize(database)

    with TestClient(
        create_app(database, clock=lambda: datetime(2030, 1, 1))
    ) as api:
        headers = {"X-User-ID": "1"}

        first = {
            "resource_id": 1,
            "start": "2030-01-02T10:00:00",
            "end": "2030-01-02T11:00:00",
            "count": 10,
        }

        assert (
            api.post(
                "/booking-series",
                headers=headers,
                json=first,
            ).status_code
            == 201
        )

        before = api.get("/bookings").json()

        second = {
            **first,
            "resource_id": 2,
            "count": 3,
        }

        response = api.post(
            "/booking-series",
            headers=headers,
            json=second,
        )

        assert response.status_code == 409
        assert response.json() == {
            "detail": "Booking quota exceeded"
        }
        assert api.get("/bookings").json() == before

        second["count"] = 2

        created = api.post(
            "/booking-series",
            headers=headers,
            json=second,
        )

        assert created.status_code == 201
        assert len(created.json()) == 2
        assert len(api.get("/bookings").json()) == 12


@pytest.mark.parametrize("value", ["0", "-1", "abc"])
def test_invalid_environment_quota(
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOKING_QUOTA_LIMIT", value)

    with pytest.raises(ValueError, match="BOOKING_QUOTA_LIMIT"):
        create_app()


def test_override_takes_precedence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("BOOKING_QUOTA_LIMIT", "5")

    database = tmp_path / "quota.sqlite3"
    initialize(database)

    with TestClient(
        create_app(
            database,
            clock=lambda: datetime(2030, 1, 1),
            quota_limit=2,
        )
    ) as api:
        body = {
            "resource_id": 1,
            "start": "2030-01-02T10:00:00",
            "end": "2030-01-02T11:00:00",
            "count": 3,
        }

        response = api.post(
            "/booking-series",
            headers={"X-User-ID": "1"},
            json=body,
        )

        assert response.status_code == 409
        assert api.get("/bookings").json() == []


# Supplementary quota acceptance tests drafted for Jaden


NOW = datetime(2030, 1, 1, 9, 0)
OWNER = {"X-User-ID": "1"}
OTHER = {"X-User-ID": "2"}
QUOTA_ERROR = {"detail": "Booking quota exceeded"}


@dataclass
class QuotaClock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@contextmanager
def quota_client(
    tmp_path: Path,
    limit: int | None = None,
) -> Iterator[tuple[TestClient, QuotaClock]]:
    database = tmp_path / "extended_quota.sqlite3"
    initialize(database)
    clock = QuotaClock()

    with TestClient(
        create_app(
            database,
            clock=clock,
            quota_limit=limit,
        )
    ) as api:
        yield api, clock


def quota_body(
    day: int,
    resource: int = 1,
) -> dict[str, Any]:
    start = NOW + timedelta(days=day)

    return {
        "resource_id": resource,
        "start": start.isoformat(),
        "end": (start + timedelta(hours=1)).isoformat(),
    }


def create_single(
    api: TestClient,
    day: int,
    resource: int = 1,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    response = api.post(
        "/bookings",
        headers=OWNER if headers is None else headers,
        json=quota_body(day, resource),
    )

    assert response.status_code == 201
    return response.json()


def assert_quota_rejection(
    api: TestClient,
    endpoint: str,
    payload: dict[str, Any],
) -> None:
    before = api.get("/bookings").json()

    response = api.post(
        endpoint,
        headers=OWNER,
        json=payload,
    )

    assert response.status_code == 409
    assert response.json() == QUOTA_ERROR
    assert api.get("/bookings").json() == before


# QT1 and QT2: Series fits or exceeds remaining quota


@pytest.mark.parametrize(
    ("count", "expected_status"),
    [(2, 201), (3, 409)],
)
def test_series_remaining_quota(
    tmp_path: Path,
    count: int,
    expected_status: int,
) -> None:
    with quota_client(tmp_path, 12) as (api, _):
        for day in range(1, 11):
            create_single(api, day)

        before = api.get("/bookings").json()

        response = api.post(
            "/booking-series",
            headers=OWNER,
            json={
                **quota_body(20, 2),
                "count": count,
            },
        )

        assert response.status_code == expected_status

        if expected_status == 201:
            occurrences = response.json()

            assert len(occurrences) == 2
            assert occurrences[0]["series_id"] is not None
            assert len({
                row["series_id"] for row in occurrences
            }) == 1

            assert all(
                row["owner_id"] == 1
                for row in occurrences
            )

            assert all(
                row["resource_id"] == 2
                for row in occurrences
            )

            assert all(
                not row["cancelled"]
                for row in occurrences
            )

            assert len(api.get("/bookings").json()) == 12

        else:
            assert response.json() == QUOTA_ERROR
            assert api.get("/bookings").json() == before


# QT3: Series fills entire quota


def test_series_fills_entire_quota(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 3) as (api, _):
        response = api.post(
            "/booking-series",
            headers=OWNER,
            json={
                **quota_body(1),
                "count": 3,
            },
        )

        assert response.status_code == 201

        occurrences = response.json()

        assert len(occurrences) == 3
        assert occurrences[0]["series_id"] is not None

        assert len({
            row["series_id"] for row in occurrences
        }) == 1

        for index, occurrence in enumerate(occurrences):
            expected_start = NOW + timedelta(
                days=1,
                weeks=index,
            )

            assert datetime.fromisoformat(
                occurrence["start"]
            ) == expected_start

            assert datetime.fromisoformat(
                occurrence["end"]
            ) == expected_start + timedelta(hours=1)

            assert occurrence["owner_id"] == 1
            assert occurrence["resource_id"] == 1
            assert occurrence["cancelled"] is False

        assert len(api.get("/bookings").json()) == 3


# QT4: Single booking rejected when quota is full


def test_single_booking_rejected_at_quota(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 3) as (api, _):
        for day in range(1, 4):
            create_single(api, day)

        assert_quota_rejection(
            api,
            "/bookings",
            quota_body(4, 2),
        )


# QT5: Series rejected when quota is full


def test_series_rejected_at_quota(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 2) as (api, _):
        create_single(api, 1)
        create_single(api, 2)

        assert_quota_rejection(
            api,
            "/booking-series",
            {
                **quota_body(3),
                "count": 1,
            },
        )


# QT6, QT7 and QT17:
# Bookings starting now, ongoing bookings and past bookings


@pytest.mark.parametrize(
    "elapsed_minutes",
    [0, 30, 120],
    ids=["exact-start", "ongoing", "past"],
)
def test_started_bookings_do_not_count_towards_quota(
    tmp_path: Path,
    elapsed_minutes: int,
) -> None:
    with quota_client(tmp_path, 1) as (api, clock):
        original = create_single(api, 1)

        clock.now = NOW + timedelta(
            days=1,
            minutes=elapsed_minutes,
        )

        replacement = create_single(api, 3, 2)

        assert replacement["id"] != original["id"]

        stored = api.get("/bookings").json()

        assert len(stored) == 2
        assert all(not row["cancelled"] for row in stored)


# QT8: Single cancellation releases quota


def test_single_cancellation_releases_quota(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 1) as (api, _):
        original = create_single(api, 1)

        response = api.post(
            f"/bookings/{original['id']}/cancel",
            headers=OWNER,
        )

        assert response.status_code == 200

        replacement = create_single(api, 2)

        stored = {
            row["id"]: row
            for row in api.get("/bookings").json()
        }

        assert len(stored) == 2
        assert stored[original["id"]]["cancelled"] is True
        assert stored[replacement["id"]]["cancelled"] is False


# QT9: Series cancellation releases quota


def test_series_cancellation_releases_quota(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 3) as (api, _):
        original = api.post(
            "/booking-series",
            headers=OWNER,
            json={
                **quota_body(1),
                "count": 3,
            },
        )

        assert original.status_code == 201

        occurrences = original.json()

        response = api.post(
            f"/bookings/{occurrences[0]['id']}/cancel?future=true",
            headers=OWNER,
        )

        assert response.status_code == 200

        replacement = api.post(
            "/booking-series",
            headers=OWNER,
            json={
                **quota_body(2, 2),
                "count": 3,
            },
        )

        assert replacement.status_code == 201
        assert len(replacement.json()) == 3

        assert (
            replacement.json()[0]["series_id"]
            != occurrences[0]["series_id"]
        )

        stored = {
            row["id"]: row
            for row in api.get("/bookings").json()
        }

        assert len(stored) == 6

        for occurrence in occurrences:
            assert stored[occurrence["id"]]["cancelled"] is True

        for occurrence in replacement.json():
            assert stored[occurrence["id"]]["cancelled"] is False


# QT10: Independent quotas for different users


def test_quota_is_independent_for_each_user(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 2) as (api, _):
        create_single(api, 1)
        create_single(api, 2)

        assert_quota_rejection(
            api,
            "/bookings",
            quota_body(3),
        )

        before = api.get("/bookings").json()

        other_booking = create_single(
            api,
            3,
            headers=OTHER,
        )

        assert other_booking["owner_id"] == 2

        stored = api.get("/bookings").json()

        owner_bookings = [
            row for row in stored
            if row["owner_id"] == 1
        ]

        assert owner_bookings == before

        assert sum(
            row["owner_id"] == 1
            for row in stored
        ) == 2

        assert sum(
            row["owner_id"] == 2
            for row in stored
        ) == 1


# QT11: Conflict validation before quota validation


def test_series_conflict_checked_before_quota(
    tmp_path: Path,
) -> None:
    with quota_client(tmp_path, 3) as (api, _):
        create_single(
            api,
            36,
            headers=OTHER,
        )

        before = api.get("/bookings").json()

        response = api.post(
            "/booking-series",
            headers=OWNER,
            json={
                **quota_body(1),
                "count": 6,
            },
        )

        assert response.status_code == 409

        assert response.json() == {
            "detail": "Resource is already booked for this interval"
        }

        assert api.get("/bookings").json() == before


# QT12: Default quota is twelve


def test_default_quota_is_twelve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(
        "BOOKING_QUOTA_LIMIT",
        raising=False,
    )

    with quota_client(tmp_path) as (api, _):
        for day in range(1, 13):
            create_single(api, day)

        assert_quota_rejection(
            api,
            "/bookings",
            quota_body(13),
        )

        assert len(api.get("/bookings").json()) == 12


# QT15: Invalid explicit quota configuration


@pytest.mark.parametrize(
    "value",
    [0, -1, 1.5, True, "abc"],
)
def test_invalid_explicit_quota(
    tmp_path: Path,
    value: Any,
) -> None:
    database = tmp_path / "invalid_quota.sqlite3"
    initialize(database)

    before = database.read_bytes()

    with pytest.raises(ValueError, match="positive integer"):
        create_app(
            database,
            quota_limit=value,
        )

    assert database.read_bytes() == before


# QT16: Explicit quota overrides environment configuration


def test_explicit_quota_overrides_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BOOKING_QUOTA_LIMIT",
        "5",
    )

    with quota_client(tmp_path, 2) as (api, _):
        create_single(api, 1)
        create_single(api, 2)

        assert_quota_rejection(
            api,
            "/bookings",
            quota_body(3),
        )

        assert len(api.get("/bookings").json()) == 2


# QT18: Environment-configured quota is enforced


def test_environment_quota_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "BOOKING_QUOTA_LIMIT",
        "5",
    )

    with quota_client(tmp_path) as (api, _):
        for day in range(1, 6):
            create_single(api, day)

        assert_quota_rejection(
            api,
            "/bookings",
            quota_body(6),
        )

        assert len(api.get("/bookings").json()) == 5


# QT19: Intentional quota-related behaviour change
# Extension-side verification


@pytest.mark.parametrize(
    "endpoint",
    ["/bookings", "/booking-series"],
)
def test_extension_rejects_booking_above_default_quota(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    monkeypatch.delenv(
        "BOOKING_QUOTA_LIMIT",
        raising=False,
    )

    with quota_client(tmp_path) as (api, _):
        for day in range(1, 13):
            create_single(api, day)

        payload = quota_body(13, 2)

        if endpoint == "/booking-series":
            payload["count"] = 1

        assert_quota_rejection(
            api,
            endpoint,
            payload,
        )

        assert len(api.get("/bookings").json()) == 12
