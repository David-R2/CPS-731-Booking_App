# Changes (Sean Huang)

Database-related:
- Added persistent per-user booking quotas, defaulting to 3 active bookings.
- Migrated existing SQLite databases to add `user.booking_quota` safely.

API-related:
- Added `GET /me/quota` to report a user's limit, active bookings, and remaining capacity.
- `POST /bookings` now returns 409 when the requester has reached their quota.

Logic-related:
- Only uncancelled bookings that have not ended count; cancellations release capacity.
- Each active occurrence in a future booking series counts as one quota slot.
- Added quota, migration, cancellation, expiry, and series-occurrence test coverage.
