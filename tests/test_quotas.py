import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from booking.database import initialize, make_engine
from booking.main import create_app
from booking.models import Booking, User

NOW = datetime(2030, 1, 15, 9)


def set_quota(database: Path, user_id: int, quota: int) -> None:
    engine = make_engine(database)
    try:
        with Session(engine) as session:
            user = session.get(User, user_id)
            assert user is not None
            user.booking_quota = quota
            session.add(user)
            session.commit()
    finally:
        engine.dispose()


def booking_body(hour: int, *, resource_id: int = 1) -> dict[str, object]:
    return {
        "resource_id": resource_id,
        "start": f"2030-01-15T{hour:02d}:00:00",
        "end": f"2030-01-15T{hour + 1:02d}:00:00",
    }


def test_quota_allows_the_limit_and_exposes_remaining_capacity(tmp_path: Path) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    with TestClient(create_app(database, clock=lambda: NOW)) as api:
        assert api.get("/me/quota", headers={"X-User-ID": "1"}).json() == {
            "booking_quota": 3,
            "active_booking_count": 0,
            "remaining_bookings": 3,
        }
        for hour in [10, 12, 14]:
            assert (
                api.post(
                    "/bookings", headers={"X-User-ID": "1"}, json=booking_body(hour)
                ).status_code
                == 201
            )
        assert api.get("/me/quota", headers={"X-User-ID": "1"}).json() == {
            "booking_quota": 3,
            "active_booking_count": 3,
            "remaining_bookings": 0,
        }
        rejected = api.post(
            "/bookings", headers={"X-User-ID": "1"}, json=booking_body(16)
        )
        assert rejected.status_code == 409
        assert rejected.json() == {"detail": "Booking quota reached"}
        assert len(api.get("/bookings").json()) == 3


def test_each_user_has_an_independent_configurable_quota(tmp_path: Path) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    set_quota(database, 1, 1)
    set_quota(database, 2, 2)
    with TestClient(create_app(database, clock=lambda: NOW)) as api:
        assert (
            api.post(
                "/bookings", headers={"X-User-ID": "1"}, json=booking_body(10)
            ).status_code
            == 201
        )
        assert (
            api.post(
                "/bookings",
                headers={"X-User-ID": "1"},
                json=booking_body(11, resource_id=2),
            ).status_code
            == 409
        )
        assert (
            api.post(
                "/bookings",
                headers={"X-User-ID": "2"},
                json=booking_body(10, resource_id=2),
            ).status_code
            == 201
        )
        assert api.get("/me/quota", headers={"X-User-ID": "2"}).json() == {
            "booking_quota": 2,
            "active_booking_count": 1,
            "remaining_bookings": 1,
        }


def test_cancelling_a_booking_restores_quota_capacity(tmp_path: Path) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    set_quota(database, 1, 1)
    with TestClient(create_app(database, clock=lambda: NOW)) as api:
        created = api.post(
            "/bookings", headers={"X-User-ID": "1"}, json=booking_body(10)
        )
        assert created.status_code == 201
        assert (
            api.post("/bookings/1/cancel", headers={"X-User-ID": "1"}).status_code
            == 200
        )
        replacement = api.post(
            "/bookings", headers={"X-User-ID": "1"}, json=booking_body(10)
        )
        assert replacement.status_code == 201
        assert replacement.json()["id"] == 2


def test_expired_bookings_do_not_consume_quota(tmp_path: Path) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    set_quota(database, 1, 1)
    engine = make_engine(database)
    try:
        with Session(engine) as session:
            session.add(
                Booking(
                    owner_id=1,
                    resource_id=1,
                    start=datetime(2030, 1, 15, 7),
                    end=datetime(2030, 1, 15, 8),
                )
            )
            session.commit()
    finally:
        engine.dispose()
    with TestClient(create_app(database, clock=lambda: NOW)) as api:
        assert api.get("/me/quota", headers={"X-User-ID": "1"}).json() == {
            "booking_quota": 1,
            "active_booking_count": 0,
            "remaining_bookings": 1,
        }
        assert (
            api.post(
                "/bookings", headers={"X-User-ID": "1"}, json=booking_body(10)
            ).status_code
            == 201
        )


def test_each_future_occurrence_in_a_series_consumes_quota(tmp_path: Path) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    set_quota(database, 1, 2)
    engine = make_engine(database)
    try:
        with Session(engine) as session:
            session.add_all(
                [
                    Booking(
                        owner_id=1,
                        resource_id=1,
                        start=datetime(2030, 1, 15, 10),
                        end=datetime(2030, 1, 15, 11),
                        series_id=100,
                    ),
                    Booking(
                        owner_id=1,
                        resource_id=1,
                        start=datetime(2030, 1, 16, 10),
                        end=datetime(2030, 1, 16, 11),
                        series_id=100,
                    ),
                ]
            )
            session.commit()
    finally:
        engine.dispose()
    with TestClient(create_app(database, clock=lambda: NOW)) as api:
        assert api.get("/me/quota", headers={"X-User-ID": "1"}).json() == {
            "booking_quota": 2,
            "active_booking_count": 2,
            "remaining_bookings": 0,
        }
        rejected = api.post(
            "/bookings",
            headers={"X-User-ID": "1"},
            json=booking_body(12, resource_id=2),
        )
        assert rejected.status_code == 409
        assert rejected.json() == {"detail": "Booking quota reached"}


def test_existing_databases_receive_the_default_quota_column(tmp_path: Path) -> None:
    database = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE user (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL)"
        )
        connection.execute("INSERT INTO user (id, name) VALUES (1, 'Legacy user')")
    initialize(database)
    engine = make_engine(database)
    try:
        with Session(engine) as session:
            user = session.get(User, 1)
            assert user is not None
            assert user.booking_quota == 3
    finally:
        engine.dispose()


def test_quota_endpoint_requires_a_known_user_and_documents_its_responses(
    tmp_path: Path,
) -> None:
    database = tmp_path / "booking.sqlite3"
    initialize(database)
    with TestClient(create_app(database, clock=lambda: NOW)) as api:
        unknown = api.get("/me/quota", headers={"X-User-ID": "99"})
        assert unknown.status_code == 404
        assert unknown.json() == {"detail": "Unknown user"}
        operation = api.get("/openapi.json").json()["paths"]["/me/quota"]["get"]
    assert set(operation["responses"]) == {"200", "404", "422"}
    assert operation["responses"]["404"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorResponse"
    }
    identity = operation["parameters"][0]
    assert identity["name"].lower() == "x-user-id"
    assert identity["required"] is True
