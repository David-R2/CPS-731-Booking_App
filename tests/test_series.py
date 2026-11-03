from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from booking.database import initialize, make_engine
from booking.main import create_app
from booking.models import Booking


@pytest.fixture
def database(tmp_path: Path) -> Path:
    path = tmp_path / "booking.sqlite3"
    initialize(path)
    engine = make_engine(path)
    with Session(engine) as session:
        session.add_all(
            [
                Booking(
                    id=12,
                    owner_id=1,
                    resource_id=1,
                    start=datetime(2030, 1, 22, 10),
                    end=datetime(2030, 1, 22, 11),
                    series_id=10,
                ),
                Booking(
                    id=10,
                    owner_id=1,
                    resource_id=1,
                    start=datetime(2030, 1, 15, 10),
                    end=datetime(2030, 1, 15, 11),
                    series_id=10,
                ),
                Booking(
                    id=11,
                    owner_id=1,
                    resource_id=1,
                    start=datetime(2030, 1, 29, 10),
                    end=datetime(2030, 1, 29, 11),
                    cancelled=True,
                    series_id=10,
                ),
                Booking(
                    id=20,
                    owner_id=1,
                    resource_id=2,
                    start=datetime(2030, 1, 15, 10),
                    end=datetime(2030, 1, 15, 11),
                ),
            ]
        )
        session.commit()
    engine.dispose()
    return path


@pytest.fixture
def client(database: Path) -> Iterator[TestClient]:
    with TestClient(create_app(database)) as api:
        yield api


def expected_series() -> list[dict[str, object]]:
    return [
        {
            "id": 10,
            "owner_id": 1,
            "resource_id": 1,
            "start": "2030-01-15T10:00:00",
            "end": "2030-01-15T11:00:00",
            "cancelled": False,
            "series_id": 10,
        },
        {
            "id": 12,
            "owner_id": 1,
            "resource_id": 1,
            "start": "2030-01-22T10:00:00",
            "end": "2030-01-22T11:00:00",
            "cancelled": False,
            "series_id": 10,
        },
        {
            "id": 11,
            "owner_id": 1,
            "resource_id": 1,
            "start": "2030-01-29T10:00:00",
            "end": "2030-01-29T11:00:00",
            "cancelled": True,
            "series_id": 10,
        },
    ]


@pytest.mark.parametrize("booking_id", [10, 11, 12])
def test_any_occurrence_returns_complete_series_chronologically(
    client: TestClient, booking_id: int
) -> None:
    response = client.get(f"/series/{booking_id}")
    assert response.status_code == 200
    assert response.json() == expected_series()


def test_series_retrieval_errors_are_documented(client: TestClient) -> None:
    missing = client.get("/series/99")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Unknown booking"}

    standalone = client.get("/series/20")
    assert standalone.status_code == 409
    assert standalone.json() == {"detail": "Booking is not part of a series"}

    operation = client.get("/openapi.json").json()["paths"]["/series/{booking_id}"][
        "get"
    ]
    assert set(operation["responses"]) == {"200", "404", "409", "422"}
    response_schema = operation["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert response_schema["items"] == {
        "$ref": "#/components/schemas/BookingSeriesRead"
    }
    assert response_schema["type"] == "array"
    for status in ["404", "409", "422"]:
        assert operation["responses"][status]["content"]["application/json"][
            "schema"
        ] == {"$ref": "#/components/schemas/ErrorResponse"}
    assert [parameter["name"] for parameter in operation["parameters"]] == [
        "booking_id"
    ]
