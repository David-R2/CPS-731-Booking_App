from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlmodel import Session, col, select

from booking.clock import campus_now
from booking.database import database_path, ensure_schema, make_engine
from booking.models import Booking, Resource, User
from booking.schemas import (
    BookingCreate,
    BookingRead,
    BookingSeriesCreate,
    BookingSeriesRead,
    ErrorResponse,
)

UserId = Annotated[int, Header(gt=0, le=9223372036854775807)]


def validate_interval(start: datetime, end: datetime, now: datetime) -> None:
    if start <= now:
        raise HTTPException(422, "Start must be in the future")
    if end <= start:
        raise HTTPException(422, "End must be after start")
    if end - start > timedelta(hours=8):
        raise HTTPException(422, "Duration must be at most eight hours")


def has_conflict(
    session: Session, resource_id: int, start: datetime, end: datetime
) -> bool:
    return (
        session.exec(
            select(Booking).where(
                Booking.resource_id == resource_id,
                col(Booking.cancelled).is_(False),
                Booking.start < end,
                Booking.end > start,
            )
        ).first()
        is not None
    )


def create_app(
    database: Path | None = None, *, clock: Callable[[], datetime] = campus_now
) -> FastAPI:
    engine = make_engine(database if database is not None else database_path())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            ensure_schema(engine)
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Campus resource booking",
        description=(
            "A course simulation of an existing system. "
            "Resource catalogue, single bookings and weekly booking series."
        ),
        lifespan=lifespan,
        responses={422: {"model": ErrorResponse}},
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422, content={"detail": "Invalid request shape or timestamp"}
        )

    @app.get("/resources", response_model=list[Resource])
    def list_resources() -> list[Resource]:
        """List persisted rooms and devices in ID order. No identity needed."""
        with Session(engine) as session:
            return list(session.exec(select(Resource).order_by(col(Resource.id))).all())

    @app.post(
        "/bookings",
        response_model=BookingRead,
        status_code=201,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def create_booking(
        request: BookingCreate,
        x_user_id: Annotated[int, Header(gt=0, le=9223372036854775807)],
    ) -> Booking:
        """Create a future booking of at most eight hours owned by X-User-ID.

        End must follow start; overnight intervals are allowed. Intervals include
        start and exclude end. Overlapping uncancelled bookings on the same
        resource return 409. Sequential requests only; simultaneous requests
        may race between availability checking and insertion.
        """
        with Session(engine) as session:
            if session.get(User, x_user_id) is None:
                raise HTTPException(404, "Unknown user")
            if session.get(Resource, request.resource_id) is None:
                raise HTTPException(404, "Unknown resource")
            validate_interval(request.start, request.end, clock())
            if has_conflict(session, request.resource_id, request.start, request.end):
                raise HTTPException(409, "Resource is already booked for this interval")
            booking = Booking(owner_id=x_user_id, **request.model_dump())
            session.add(booking)
            session.commit()
            session.refresh(booking)
            return booking

    @app.post(
        "/booking-series",
        response_model=list[BookingSeriesRead],
        status_code=201,
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def create_booking_series(
        request: BookingSeriesCreate,
        x_user_id: UserId,
    ) -> list[Booking]:
        with Session(engine) as session:
            if session.get(User, x_user_id) is None:
                raise HTTPException(404, "Unknown user")
            if session.get(Resource, request.resource_id) is None:
                raise HTTPException(404, "Unknown resource")
            now = clock()
            occurrences = [
                (
                    request.start + timedelta(weeks=index),
                    request.end + timedelta(weeks=index),
                )
                for index in range(request.count)
            ]
            for start, end in occurrences:
                validate_interval(start, end, now)
                if has_conflict(session, request.resource_id, start, end):
                    raise HTTPException(
                        409, "Resource is already booked for this interval"
                    )
            first_start, first_end = occurrences[0]
            first = Booking(
                owner_id=x_user_id,
                resource_id=request.resource_id,
                start=first_start,
                end=first_end,
            )
            session.add(first)
            session.flush()
            if first.id is None:
                raise RuntimeError("Booking ID was not generated")
            first.series_id = first.id
            bookings = [first]
            for start, end in occurrences[1:]:
                booking = Booking(
                    owner_id=x_user_id,
                    resource_id=request.resource_id,
                    start=start,
                    end=end,
                    series_id=first.id,
                )
                session.add(booking)
                bookings.append(booking)
            session.commit()
            for booking in bookings:
                session.refresh(booking)
            return bookings

    @app.get("/bookings", response_model=list[BookingRead])
    def list_bookings() -> list[Booking]:
        """List all bookings, including cancelled records, in ID order."""
        with Session(engine) as session:
            return list(session.exec(select(Booking).order_by(col(Booking.id))).all())

    @app.get(
        "/bookings/{booking_id}",
        response_model=BookingRead,
        responses={404: {"model": ErrorResponse}},
    )
    def get_booking(
        booking_id: Annotated[int, ApiPath(gt=0, le=9223372036854775807)],
    ) -> Booking:
        """Retrieve one booking. No identity needed."""
        with Session(engine) as session:
            booking = session.get(Booking, booking_id)
            if booking is None:
                raise HTTPException(404, "Unknown booking")
            return booking

    @app.post(
        "/bookings/{booking_id}/cancel",
        response_model=BookingRead,
        responses={
            403: {"model": ErrorResponse},
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def cancel_booking(
        booking_id: Annotated[int, ApiPath(gt=0, le=9223372036854775807)],
        x_user_id: Annotated[int, Header(gt=0, le=9223372036854775807)],
    ) -> Booking:
        """Cancel one booking as its owner using X-User-ID; no body is needed.

        Active bookings can be cancelled only strictly before start (409
        otherwise). Retain the cancelled record and release its resource slot.
        Owner retries return the unchanged record even after the original start;
        other users receive 403, including on retries. Unknown users/bookings
        return 404. Check ownership, then cancelled state, then start time.
        """
        with Session(engine) as session:
            if session.get(User, x_user_id) is None:
                raise HTTPException(404, "Unknown user")
            booking = session.get(Booking, booking_id)
            if booking is None:
                raise HTTPException(404, "Unknown booking")
            if booking.owner_id != x_user_id:
                raise HTTPException(403, "Only the owner can cancel this booking")
            if booking.cancelled:
                return booking
            if booking.start <= clock():
                raise HTTPException(409, "Booking has already started")
            booking.cancelled = True
            session.add(booking)
            session.commit()
            session.refresh(booking)
            return booking

    return app
