from typing import Annotated

from fastapi import APIRouter, HTTPException
from fastapi import Path as ApiPath
from sqlalchemy import Engine
from sqlmodel import Session, col, select

from booking.models import Booking
from booking.schemas import BookingSeriesRead, ErrorResponse


def create_series_router(engine: Engine) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/series/{booking_id}",
        response_model=list[BookingSeriesRead],
        responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
    )
    def get_series(
        booking_id: Annotated[int, ApiPath(gt=0, le=9223372036854775807)],
    ) -> list[Booking]:
        """Retrieve a complete series from any occurrence's booking ID.

        No identity is needed. All occurrences, including cancelled records, are
        returned in chronological order. Unknown bookings return 404; a
        standalone booking returns 409 because it has no series.
        """
        with Session(engine) as session:
            booking = session.get(Booking, booking_id)
            if booking is None:
                raise HTTPException(404, "Unknown booking")
            series_id = booking.series_id
            if series_id is None:
                raise HTTPException(409, "Booking is not part of a series")
            return list(
                session.exec(
                    select(Booking)
                    .where(Booking.series_id == series_id)
                    .order_by(col(Booking.start), col(Booking.id))
                ).all()
            )

    return router
