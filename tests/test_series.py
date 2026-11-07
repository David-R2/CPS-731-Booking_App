"""Common-core tests for weekly recurring reservations (C1-C12, Appendix A).

These tests use only the published HTTP contract: POST /series,
GET /series/{series_id}, POST /series/{series_id}/cancel and the existing
booking endpoints. They never assume a particular ID allocation order, and
every rejection test checks the stored state afterwards, not just the status.

Dates are April-June 2030, away from daylight-saving transitions.
2030-04-01 is a Monday.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from booking.database import initialize
from booking.main import create_app

OWNER = {"X-User-ID": "1"}
OTHER = {"X-User-ID": "2"}
START = datetime(2030, 4, 1, 10)  # Monday 10:00
BEFORE_START = datetime(2030, 3, 25, 9)  # default controlled "now"


@dataclass
class Clock:
    """Controllable clock passed to create_app (C12)."""

    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Env:
    api: TestClient
    clock: Clock
    database: Path


@pytest.fixture
def env(tmp_path: Path) -> Iterator[Env]:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    clock = Clock(BEFORE_START)
    with TestClient(create_app(database, clock=clock)) as api:
        yield Env(api, clock, database)


def ts(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def series_body(
    start: datetime = START,
    hours: float = 1,
    count: Any = 3,
    resource_id: Any = 1,
) -> dict[str, Any]:
    return {
        "resource_id": resource_id,
        "start": ts(start),
        "end": ts(start + timedelta(hours=hours)),
        "count": count,
    }


def single_body(start: datetime, end: datetime, resource_id: int = 1) -> dict[str, Any]:
    return {"resource_id": resource_id, "start": ts(start), "end": ts(end)}


def create_series(env: Env, **kwargs: Any) -> list[dict[str, Any]]:
    response = env.api.post("/booking-series", headers=OWNER, json=series_body(**kwargs))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def bookings(env: Env) -> list[dict[str, Any]]:
    response = env.api.get("/bookings")
    assert response.status_code == 200
    result: list[dict[str, Any]] = response.json()
    return result


def assert_rejected_without_changes(
    env: Env, body: dict[str, Any], status: int, headers: dict[str, str] = OWNER
) -> None:
    """Reject the request AND leave every stored booking exactly as it was."""
    before = bookings(env)
    response = env.api.post("/booking-series", headers=headers, json=body)
    assert response.status_code == status, response.text
    assert isinstance(response.json()["detail"], str)
    assert bookings(env) == before


# ---------------------------------------------------------------- creation (C1-C3)


@pytest.mark.parametrize("count", [1, 12])
def test_count_boundaries_create_weekly_occurrences(env: Env, count: int) -> None:
    series = create_series(env, count=count)

    assert len(series) == count
    assert len({occurrence["id"] for occurrence in series}) == count

    for week, occurrence in enumerate(series):
        start = START + timedelta(weeks=week)
        assert occurrence == {
            "id": occurrence["id"],
            "owner_id": 1,
            "resource_id": 1,
            "start": ts(start),
            "end": ts(start + timedelta(hours=1)),
            "cancelled": False,
            "series_id": series[0]["series_id"],
        }
        assert datetime.fromisoformat(occurrence["start"]).weekday() == 0


@pytest.mark.parametrize("count", [0, 13, -1, True, "3", 3.5, None])
def test_invalid_count_is_rejected_without_changes(env: Env, count: Any) -> None:
    assert_rejected_without_changes(env, series_body(count=count), 422)


@pytest.mark.parametrize(
    "extra",
    [{"owner_id": 2}, {"id": 99}, {"cancelled": True}, {"recurrence_count": 3}],
)
def test_unknown_fields_are_rejected(env: Env, extra: dict[str, Any]) -> None:
    assert_rejected_without_changes(env, {**series_body(), **extra}, 422)


@pytest.mark.parametrize("missing", ["resource_id", "start", "end", "count"])
def test_missing_fields_are_rejected(env: Env, missing: str) -> None:
    body = series_body()
    del body[missing]
    assert_rejected_without_changes(env, body, 422)


def test_acting_user_owns_series_and_occurrences(env: Env) -> None:
    response = env.api.post("/booking-series", headers=OTHER, json=series_body())
    assert response.status_code == 201
    series = response.json()
    assert all(booking["owner_id"] == 2 for booking in series)
    assert {o["owner_id"] for o in series} == {2}


@pytest.mark.parametrize(
    ("headers", "status"),
    [
        ({}, 422),
        ({"X-User-ID": "abc"}, 422),
        ({"X-User-ID": "0"}, 422),
        ({"X-User-ID": "999"}, 404),
    ],
)
def test_bad_or_unknown_user(env: Env, headers: dict[str, str], status: int) -> None:
    assert_rejected_without_changes(env, series_body(), status, headers=headers)


@pytest.mark.parametrize(("resource_id", "status"), [(999, 404), (0, 422), ("1", 422)])
def test_bad_or_unknown_resource(env: Env, resource_id: Any, status: int) -> None:
    assert_rejected_without_changes(env, series_body(resource_id=resource_id), status)


def test_start_exactly_now_is_rejected(env: Env) -> None:
    env.clock.now = START
    assert_rejected_without_changes(env, series_body(), 422)


def test_start_just_after_now_is_accepted(env: Env) -> None:
    env.clock.now = START - timedelta(microseconds=1)
    create_series(env, count=1)


def test_start_in_past_is_rejected(env: Env) -> None:
    env.clock.now = START + timedelta(hours=1)
    assert_rejected_without_changes(env, series_body(), 422)


def test_end_equal_to_or_before_start_is_rejected(env: Env) -> None:
    assert_rejected_without_changes(env, series_body(hours=0), 422)
    assert_rejected_without_changes(env, series_body(hours=-1), 422)


def test_duration_limit_and_overnight(env: Env) -> None:
    night = datetime(2030, 4, 1, 22)
    exactly_eight = series_body(start=night, hours=8)  # 22:00 -> 06:00 next day
    too_long = {**exactly_eight, "end": "2030-04-02T06:01:00"}

    assert_rejected_without_changes(env, too_long, 422)
    response = env.api.post("/booking-series", headers=OWNER, json=exactly_eight)
    assert response.status_code == 201
    first = response.json()[0]
    assert (first["start"], first["end"]) == (
        "2030-04-01T22:00:00",
        "2030-04-02T06:00:00",
    )


@pytest.mark.parametrize(
    "start",
    [
        "2030-04-01T10:00:00Z",
        "2030-04-01T10:00:00-04:00",
        "2030-04-01 10:00:00",
        "2030-04-01T10:00",
    ],
)
def test_non_campus_timestamp_formats_are_rejected(env: Env, start: str) -> None:
    body = {**series_body(), "start": start}
    assert_rejected_without_changes(env, body, 422)


def test_fractional_seconds_are_accepted(env: Env) -> None:
    body = {**series_body(count=1), "start": "2030-04-01T10:00:00.123456"}
    assert env.api.post("/booking-series", headers=OWNER, json=body).status_code == 201


# ------------------------------------------------- conflicts & all-or-nothing (C4, C5)


def test_adjacent_booking_does_not_conflict_but_one_minute_overlap_does(
    env: Env,
) -> None:
    existing = single_body(datetime(2030, 4, 1, 9), START)  # 09:00-10:00
    assert env.api.post("/bookings", headers=OTHER, json=existing).status_code == 201

    overlap = series_body(start=START - timedelta(minutes=1), count=1)  # 09:59
    assert_rejected_without_changes(env, overlap, 409)
    create_series(env, count=1)  # 10:00 starts exactly when 09:00-10:00 ends


def test_same_interval_on_other_resource_does_not_conflict(env: Env) -> None:
    create_series(env, resource_id=1)
    create_series(env, resource_id=2)


def test_conflict_on_last_occurrence_rejects_whole_series(env: Env) -> None:
    sixth = START + timedelta(weeks=5)
    existing = env.api.post(
        "/bookings",
        headers=OTHER,
        json=single_body(sixth + timedelta(minutes=30), sixth + timedelta(hours=2)),
    )
    assert existing.status_code == 201

    assert_rejected_without_changes(env, series_body(count=6), 409)
    assert bookings(env) == [existing.json()]
    # Weeks 1-5 were free and must still be free (nothing partial was stored).
    create_series(env, count=5)


def test_conflict_with_other_series_rejects_without_changing_it(env: Env) -> None:
    first = create_series(env, count=3)
    overlapping_week_two = series_body(
        start=START + timedelta(weeks=1, minutes=30), count=3
    )

    assert_rejected_without_changes(env, overlapping_week_two, 409)
    assert env.api.get(f"/series/{first[0]['id']}").json() == first


def test_identical_request_twice_is_rejected_second_time(env: Env) -> None:
    create_series(env)
    assert_rejected_without_changes(env, series_body(), 409)
    assert len(bookings(env)) == 3


def test_cancelled_booking_does_not_block_series(env: Env) -> None:
    single = env.api.post(
        "/bookings", headers=OTHER, json=single_body(START, START + timedelta(hours=1))
    ).json()
    assert (
        env.api.post(f"/bookings/{single['id']}/cancel", headers=OTHER).status_code
        == 200
    )
    create_series(env)


# ------------------------------------------------------------ reads & persistence (C6)


def test_occurrences_are_ordinary_bookings(env: Env) -> None:
    series = create_series(env)
    listed = bookings(env)
    for occurrence in series:
        assert any(
    booking == {key: value for key, value in occurrence.items() if key != "series_id"}
    for booking in listed
)
        fetched = env.api.get(f"/bookings/{occurrence['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == {
    key: value for key, value in occurrence.items() if key != "series_id"
} # existing shape, no extra fields


def test_get_series_needs_no_identity_and_matches_creation(env: Env) -> None:
    series = create_series(env)

    response = env.api.get(f"/series/{series[0]['id']}")

    assert response.status_code == 200
    assert response.json() == series


@pytest.mark.parametrize(("series_id", "status"), [(999999, 404), (0, 422), ("x", 422)])
def test_get_series_bad_or_unknown_id(env: Env, series_id: Any, status: int) -> None:
    response = env.api.get(f"/series/{series_id}")
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)


def test_series_survives_restart_with_cancellation_state(tmp_path: Path) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    with TestClient(create_app(database, clock=Clock(BEFORE_START))) as api:
        created = api.post("/booking-series", headers=OWNER, json=series_body())
        assert created.status_code == 201
        series = created.json()
        second = series[1]
        assert (
            api.post(f"/bookings/{second['id']}/cancel", headers=OWNER).status_code
            == 200
        )
        expected = api.get(f"/series/{series[0]['id']}").json()
        all_bookings = api.get("/bookings").json()

    with TestClient(create_app(database, clock=Clock(BEFORE_START))) as restarted:
        assert restarted.get(f"/series/{series[0]['id']}").json() == expected
        assert restarted.get("/bookings").json() == all_bookings
        assert [o["cancelled"] for o in expected] == [False, True, False]


# ------------------------------------------------------- single bookings (C10)


def test_single_booking_cannot_overlap_occurrence(env: Env) -> None:
    series = create_series(env)
    before = bookings(env)
    third = START + timedelta(weeks=2)
    response = env.api.post(
        "/bookings",
        headers=OTHER,
        json=single_body(third + timedelta(minutes=15), third + timedelta(minutes=45)),
    )
    assert response.status_code == 409
    assert bookings(env) == before
    assert env.api.get(f"/series/{series['id']}").json() == series


def test_single_booking_contract_unchanged(env: Env) -> None:
    response = env.api.post(
        "/bookings", headers=OWNER, json=single_body(START, START + timedelta(hours=1))
    )
    assert response.status_code == 201
    assert set(response.json()) == {
        "id",
        "owner_id",
        "resource_id",
        "start",
        "end",
        "cancelled",
    }
    extra = {**single_body(START, START + timedelta(hours=1)), "count": 2}
    assert env.api.post("/bookings", headers=OWNER, json=extra).status_code == 422


# ------------------------------------------------- single-occurrence cancel (C7, C9)


def test_cancel_one_occurrence_leaves_others_and_releases_slot(env: Env) -> None:
    series = create_series(env)
    second = series["occurrences"][1]

    response = env.api.post(f"/bookings/{second['id']}/cancel", headers=OWNER)
    assert response.status_code == 200
    assert response.json() == {**second, "cancelled": True}

    after = env.api.get(f"/series/{series['id']}").json()
    assert [o["cancelled"] for o in after["occurrences"]] == [False, True, False]
    assert len(after["occurrences"]) == 3  # cancelled record retained (C9)

    # Another user can take the released slot; other weeks stay reserved.
    released = datetime.fromisoformat(second["start"])
    taken = env.api.post(
        "/bookings",
        headers=OTHER,
        json=single_body(released, released + timedelta(hours=1)),
    )
    assert taken.status_code == 201
    blocked = env.api.post(
        "/bookings", headers=OTHER, json=single_body(START, START + timedelta(hours=1))
    )
    assert blocked.status_code == 409


def test_cancel_occurrence_just_before_start_succeeds(env: Env) -> None:
    first = create_series(env)["occurrences"][0]
    env.clock.now = START - timedelta(microseconds=1)
    response = env.api.post(f"/bookings/{first['id']}/cancel", headers=OWNER)
    assert response.status_code == 200
    assert response.json()["cancelled"] is True


def test_cancel_occurrence_exactly_at_start_fails(env: Env) -> None:
    first = create_series(env)["occurrences"][0]
    env.clock.now = START
    response = env.api.post(f"/bookings/{first['id']}/cancel", headers=OWNER)
    assert response.status_code == 409
    assert env.api.get(f"/bookings/{first['id']}").json() == first


def test_non_owner_cannot_cancel_occurrence_even_after_cancellation(env: Env) -> None:
    first = create_series(env)["occurrences"][0]
    assert (
        env.api.post(f"/bookings/{first['id']}/cancel", headers=OTHER).status_code
        == 403
    )
    assert env.api.get(f"/bookings/{first['id']}").json() == first

    cancelled = env.api.post(f"/bookings/{first['id']}/cancel", headers=OWNER).json()
    assert (
        env.api.post(f"/bookings/{first['id']}/cancel", headers=OTHER).status_code
        == 403
    )
    repeat = env.api.post(f"/bookings/{first['id']}/cancel", headers=OWNER)
    assert repeat.status_code == 200
    assert repeat.json() == cancelled


# ------------------------------------------------------ series cancel (C8, C9)


def test_series_cancel_only_affects_future_occurrences(env: Env) -> None:
    series = create_series(env, count=4)
    ids = [o["id"] for o in series["occurrences"]]
    # Week 1 is past, week 2 is ongoing (now = 10:30 on its day), weeks 3-4 future.
    env.clock.now = START + timedelta(weeks=1, minutes=30)

    response = env.api.post(f"/series/{series['id']}/cancel", headers=OWNER)
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == series["id"]
    assert [o["id"] for o in body["occurrences"]] == ids
    assert [o["cancelled"] for o in body["occurrences"]] == [False, False, True, True]
    assert env.api.get(f"/series/{series['id']}").json() == body
    assert len(bookings(env)) == 4  # nothing deleted


def test_series_cancel_occurrence_starting_exactly_now_is_kept(env: Env) -> None:
    series = create_series(env, count=2)
    env.clock.now = START  # week 1 starts exactly now: ongoing, not future
    body = env.api.post(f"/booking-series/{series['id']}/cancel", headers=OWNER).json()
    assert [o["cancelled"] for o in body["occurrences"]] == [False, True]


def test_series_cancel_preserves_already_cancelled_and_is_idempotent(env: Env) -> None:
    series = create_series(env)
    first = series["occurrences"][0]
    env.api.post(f"/bookings/{first['id']}/cancel", headers=OWNER)

    once = env.api.post(f"/booking-series/{series['id']}/cancel", headers=OWNER)
    assert once.status_code == 200
    assert all(o["cancelled"] for o in once.json()["occurrences"])
    snapshot = bookings(env)

    twice = env.api.post(f"/series/{series['id']}/cancel", headers=OWNER)
    assert twice.status_code == 200
    assert twice.json() == once.json()
    assert bookings(env) == snapshot


def test_series_cancel_with_no_future_occurrences_changes_nothing(env: Env) -> None:
    series = create_series(env, count=2)
    env.clock.now = START + timedelta(weeks=3)
    response = env.api.post(f"/booking-series/{series['id']}/cancel", headers=OWNER)
    assert response.status_code == 200
    assert response.json() == series


def test_series_cancel_releases_slots_for_new_bookings(env: Env) -> None:
    series = create_series(env)
    env.api.post(f"/booking-series/{series['id']}/cancel", headers=OWNER)
    response = env.api.post("/booking-series", headers=OTHER, json=series_body())
    assert response.status_code == 201


def test_non_owner_cannot_cancel_series_even_after_cancellation(env: Env) -> None:
    series = create_series(env)
    before = bookings(env)
    response = env.api.post(f"/booking-series/{series['id']}/cancel", headers=OTHER)
    assert response.status_code == 403
    assert bookings(env) == before

    env.api.post(f"/booking-series/{series['id']}/cancel", headers=OWNER)
    after_owner = bookings(env)
    assert (
        env.api.post(f"/booking-series/{series['id']}/cancel", headers=OTHER).status_code == 403
    )
    assert bookings(env) == after_owner


@pytest.mark.parametrize(
    ("path", "headers", "status"),
    [
        ("/series/999999/cancel", OWNER, 404),
        ("/series/0/cancel", OWNER, 422),
        ("{id}", {"X-User-ID": "999"}, 404),
        ("{id}", {}, 422),
    ],
)
def test_series_cancel_bad_input(
    env: Env, path: str, headers: dict[str, str], status: int
) -> None:
    series = create_series(env)
    if path == "{id}":
        path = f"/series/{series['id']}/cancel"
    before = bookings(env)
    response = env.api.post(path, headers=headers)
    assert response.status_code == status
    assert isinstance(response.json()["detail"], str)
    assert bookings(env) == before
