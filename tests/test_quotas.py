"""Per-user booking quota extension (docs/extension-plan.md, Q1-Q8, QT1-QT12).

Each test controls the clock and the quota limit through create_app, and every
rejection also checks that the stored bookings are unchanged. Dates are in
April-June 2030, away from daylight-saving transitions; 2030-04-01 is a Monday.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from booking.database import initialize
from booking.main import DEFAULT_QUOTA_LIMIT, QUOTA_LIMIT_ENV, create_app

USER_1 = {"X-User-ID": "1"}
USER_2 = {"X-User-ID": "2"}
START = datetime(2030, 4, 1, 10)  # Monday 10:00
NOW = datetime(2030, 3, 25, 9)  # default controlled "now", a week earlier
QUOTA_ERROR = {"detail": "Booking quota exceeded"}


@dataclass
class Clock:
    now: datetime

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Env:
    api: TestClient
    clock: Clock


def ts(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def single(start: datetime, resource_id: int = 1, hours: int = 1) -> dict[str, Any]:
    return {
        "resource_id": resource_id,
        "start": ts(start),
        "end": ts(start + timedelta(hours=hours)),
    }


def series(start: datetime, count: int, resource_id: int = 1) -> dict[str, Any]:
    return {**single(start, resource_id), "count": count}


def make_env(tmp_path: Path, quota_limit: int | None) -> Iterator[Env]:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    clock = Clock(NOW)
    with TestClient(create_app(database, clock=clock, quota_limit=quota_limit)) as api:
        yield Env(api, clock)


@pytest.fixture
def env12(tmp_path: Path) -> Iterator[Env]:
    yield from make_env(tmp_path, 12)


@pytest.fixture
def env3(tmp_path: Path) -> Iterator[Env]:
    yield from make_env(tmp_path, 3)


@pytest.fixture
def env2(tmp_path: Path) -> Iterator[Env]:
    yield from make_env(tmp_path, 2)


@pytest.fixture
def env1(tmp_path: Path) -> Iterator[Env]:
    yield from make_env(tmp_path, 1)


def bookings(env: Env) -> list[dict[str, Any]]:
    response = env.api.get("/bookings")
    assert response.status_code == 200
    result: list[dict[str, Any]] = response.json()
    return result


def future_count(env: Env, owner_id: int = 1) -> int:
    return sum(
        1
        for b in bookings(env)
        if b["owner_id"] == owner_id
        and not b["cancelled"]
        and datetime.fromisoformat(b["start"]) > env.clock.now
    )


def book_singles(env: Env, n: int, headers: dict[str, str] = USER_1) -> None:
    """Create n one-hour single bookings on consecutive days (resources 1-2)."""
    for day in range(n):
        body = single(START + timedelta(days=day), resource_id=1 + day % 2)
        response = env.api.post("/bookings", headers=headers, json=body)
        assert response.status_code == 201, response.text


def assert_quota_rejected(
    env: Env, path: str, body: dict[str, Any], headers: dict[str, str] = USER_1
) -> None:
    before = bookings(env)
    response = env.api.post(path, headers=headers, json=body)
    assert response.status_code == 409, response.text
    assert response.json() == QUOTA_ERROR
    assert bookings(env) == before


# ------------------------------------------------- brief example (Q1, Q5, Q6)


def test_qt1_ten_plus_two_reaches_exactly_twelve(env12: Env) -> None:
    book_singles(env12, 10)
    response = env12.api.post(
        "/booking-series", headers=USER_1, json=series(START + timedelta(weeks=3), 2)
    )
    assert response.status_code == 201
    assert len(response.json()) == 2
    assert future_count(env12) == 12


def test_qt2_ten_plus_three_is_rejected_and_count_stays_ten(env12: Env) -> None:
    book_singles(env12, 10)
    body = series(START + timedelta(weeks=3), 3)
    assert_quota_rejected(env12, "/booking-series", body)
    assert future_count(env12) == 10
    assert len(bookings(env12)) == 10  # no occurrence of the rejected series


# --------------------------------------------------- boundaries (Q1, Q2, Q5)


def test_qt3_series_exactly_at_limit_is_accepted(env3: Env) -> None:
    response = env3.api.post("/booking-series", headers=USER_1, json=series(START, 3))
    assert response.status_code == 201
    assert future_count(env3) == 3


def test_qt3b_series_one_over_limit_is_rejected(env3: Env) -> None:
    assert_quota_rejected(env3, "/booking-series", series(START, 4))
    assert bookings(env3) == []


def test_qt4_quota_counts_across_resources_and_blocks_singles(env3: Env) -> None:
    book_singles(env3, 3)  # alternates resources 1 and 2
    assert {b["resource_id"] for b in bookings(env3)} == {1, 2}
    body = single(START + timedelta(days=10), resource_id=3)
    assert_quota_rejected(env3, "/bookings", body)


def test_qt5_single_bookings_count_against_series(env2: Env) -> None:
    book_singles(env2, 2)
    assert_quota_rejected(
        env2, "/booking-series", series(START + timedelta(weeks=2), 1, resource_id=3)
    )


# ----------------------------------------------------------- time (Q3)


def test_qt6_booking_starting_exactly_now_no_longer_counts(env1: Env) -> None:
    book_singles(env1, 1)
    env1.clock.now = START  # the booking starts exactly now
    assert future_count(env1) == 0
    later = single(START + timedelta(days=3), resource_id=2)
    assert env1.api.post("/bookings", headers=USER_1, json=later).status_code == 201


def test_qt6b_booking_one_microsecond_in_future_still_counts(env1: Env) -> None:
    book_singles(env1, 1)
    env1.clock.now = START - timedelta(microseconds=1)
    later = single(START + timedelta(days=3), resource_id=2)
    assert_quota_rejected(env1, "/bookings", later)


def test_qt7_ongoing_and_past_bookings_do_not_count(env1: Env) -> None:
    book_singles(env1, 1)
    env1.clock.now = START + timedelta(minutes=30)  # ongoing
    ongoing = single(START + timedelta(days=3), resource_id=2)
    assert env1.api.post("/bookings", headers=USER_1, json=ongoing).status_code == 201
    env1.clock.now = START + timedelta(days=5)  # both are now past
    later = single(START + timedelta(days=6), resource_id=2)
    assert env1.api.post("/bookings", headers=USER_1, json=later).status_code == 201


# ----------------------------------------------------- cancellation (Q4)


def test_qt8_cancelling_a_single_booking_releases_quota(env1: Env) -> None:
    book_singles(env1, 1)
    booking_id = bookings(env1)[0]["id"]
    blocked = single(START + timedelta(days=3), resource_id=2)
    assert_quota_rejected(env1, "/bookings", blocked)

    cancel = env1.api.post(f"/bookings/{booking_id}/cancel", headers=USER_1)
    assert cancel.status_code == 200
    assert env1.api.post("/bookings", headers=USER_1, json=blocked).status_code == 201


def test_qt9_series_cancellation_releases_quota(env3: Env) -> None:
    created = env3.api.post("/booking-series", headers=USER_1, json=series(START, 3))
    assert created.status_code == 201
    first_id = created.json()[0]["id"]
    again = series(START + timedelta(days=1), 3, resource_id=2)
    assert_quota_rejected(env3, "/booking-series", again)

    cancel = env3.api.post(
        f"/bookings/{first_id}/cancel", headers=USER_1, params={"future": "true"}
    )
    assert cancel.status_code == 200
    assert future_count(env3) == 0
    assert env3.api.post("/booking-series", headers=USER_1, json=again).status_code == (
        201
    )


def test_qt9b_cancelling_one_occurrence_frees_exactly_one_place(env3: Env) -> None:
    created = env3.api.post("/booking-series", headers=USER_1, json=series(START, 3))
    second_id = created.json()[1]["id"]
    assert env3.api.post(
        f"/bookings/{second_id}/cancel", headers=USER_1
    ).status_code == (200)
    assert future_count(env3) == 2
    one_more = single(START + timedelta(days=1), resource_id=2)
    assert env3.api.post("/bookings", headers=USER_1, json=one_more).status_code == 201
    two_more = series(START + timedelta(days=2), 1, resource_id=3)
    assert_quota_rejected(env3, "/booking-series", two_more)


# ---------------------------------------------------- per user (Q1)


def test_qt10_quota_is_per_user(env2: Env) -> None:
    book_singles(env2, 2, headers=USER_1)
    assert_quota_rejected(env2, "/bookings", single(START + timedelta(days=5)))
    other = single(START + timedelta(days=5))
    response = env2.api.post("/bookings", headers=USER_2, json=other)
    assert response.status_code == 201
    assert response.json()["owner_id"] == 2


# ------------------------------------------------- error precedence (A3)


def test_qt11_slot_conflict_is_reported_before_quota(env3: Env) -> None:
    sixth = START + timedelta(weeks=5)
    taken = env3.api.post("/bookings", headers=USER_2, json=single(sixth))
    assert taken.status_code == 201
    before = bookings(env3)
    response = env3.api.post("/booking-series", headers=USER_1, json=series(START, 6))
    assert response.status_code == 409
    assert response.json() == {"detail": "Resource is already booked for this interval"}
    assert bookings(env3) == before


def test_qt11b_validation_errors_are_unchanged_by_quota(env1: Env) -> None:
    book_singles(env1, 1)
    past = single(NOW - timedelta(days=1), resource_id=2)
    response = env1.api.post("/bookings", headers=USER_1, json=past)
    assert response.status_code == 422
    unknown = env1.api.post(
        "/bookings", headers={"X-User-ID": "999"}, json=single(START, resource_id=2)
    )
    assert unknown.status_code == 404


# --------------------------------------------------- configuration (A4)


def test_qt12_default_limit_is_twelve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(QUOTA_LIMIT_ENV, raising=False)
    assert DEFAULT_QUOTA_LIMIT == 12
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    clock = Clock(NOW)
    with TestClient(create_app(database, clock=clock)) as api:
        env = Env(api, clock)
        response = api.post("/booking-series", headers=USER_1, json=series(START, 12))
        assert response.status_code == 201
        extra = single(START + timedelta(days=1), resource_id=2)
        assert_quota_rejected(env, "/bookings", extra)


def test_qt12b_limit_can_be_set_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(QUOTA_LIMIT_ENV, "2")
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    with TestClient(create_app(database, clock=Clock(NOW))) as api:
        assert api.post(
            "/booking-series", headers=USER_1, json=series(START, 2)
        ).status_code == (201)
        response = api.post(
            "/bookings", headers=USER_1, json=single(START + timedelta(days=1), 2)
        )
        assert response.status_code == 409


@pytest.mark.parametrize("bad_limit", [0, -1])
def test_qt12c_limit_below_one_is_refused(tmp_path: Path, bad_limit: int) -> None:
    with pytest.raises(ValueError):
        create_app(tmp_path / "booking.sqlite3", quota_limit=bad_limit)
