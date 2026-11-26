# Extension design as built: per-user booking quotas

The pre-implementation plan is [`extension-plan.md`](extension-plan.md). This
file describes what was actually built, what changed from the plan and why, and
the known limitations.

## 1. Design as built (`booking/main.py`)

| Element | Responsibility |
|---|---|
| `booking_quota(quota_limit)` | Resolves the limit: an explicit `quota_limit` argument, else the `BOOKING_QUOTA_LIMIT` environment variable, else **12**. Rejects 0, negative, boolean or non-integer values with `ValueError` before the app handles any request. |
| `future_booking_count(session, owner_id, now)` | One `COUNT` query: the owner's bookings that are **uncancelled and start strictly after `now`**, across all resources. |
| `create_app(..., quota_limit=None)` | Calls `booking_quota()` once at start-up and keeps the result. |
| `check_quota(session, owner_id, now, requested)` | Raises **409 `Booking quota exceeded`** if `future_booking_count(...) + requested > quota`. |
| `POST /bookings` | Runs the existing user, resource, time and conflict checks first, then `check_quota(..., 1)`, then inserts. |
| `POST /booking-series` | Validates and conflict-checks **every** occurrence, then `check_quota(..., n)` with n = number of occurrences, then inserts all rows and commits once. A rejected series stores nothing. |
| Cancellation and reads | **Unchanged.** A cancelled booking stops counting automatically because the count only reads `cancelled = false`. |

**No data-model change:** no quota column and no migration. The count is
derived from existing `Booking` rows, so cancelling a booking or time passing
needs no extra writes.

## 2. Changes from the plan, and why

| Change | Why | Where |
|---|---|---|
| **Two implementations of the configuration and count were merged side by side, then consolidated.** Sean Rodriguez's PR #15 added `booking_quota()` and `future_booking_count()`. The series work (Sean Huang, PR #16, brought into `main` through commit `0da91c1`) added its own environment parsing in `create_app` and its own count query in `check_quota`. After merging, the helpers from #15 were defined but unused. | Two copies of the same rule risk drifting apart. We kept the plan's design ("a shared quota-count helper and configuration", plan §7 step 2): `create_app` now calls `booking_quota()`, and `check_quota` calls `future_booking_count()`. 23 lines removed; all 118 tests and the 13-bug mutation check still pass. | quota tidy-up commit |
| **Pre-existing ruff failures fixed** (2 errors, 4 files on `main`). | The required checks must pass. Formatting only, no behaviour change. | `c9e2e2a` |
| **Unplanned: series dates beyond the supported calendar range now return 422** (`Series dates exceed the supported range`) instead of an unhandled `OverflowError` (server error). | Found while implementing series quota checks: a very late start plus `count` weeks can overflow `datetime`. A 422 matches the core's handling of invalid input. Test: `test_series_dates_beyond_datetime_range_are_rejected` in `tests/test_series.py`. | `0da91c1` |
| **Tests combine two sets**: Sean Huang's original quota tests and the QT-labelled acceptance tests (Jaden Rajan George), in one file. | Both cover the plan; keeping both adds independent checks of the same rules. Mapping to QT IDs is in `extension-verification.md` §3. | `0967666`, `693fccb` |
| **QT13 and QT14 are recorded runs, not separate test functions.** | They are the full suite and the four checks; results are in `extension-verification.md` §2. | n/a |

Nothing else deviates from the plan. Single bookings are limited as well as
series, the check runs after the core checks and before any insert, and the
409 message and configuration names are as planned.

## 3. Design decisions and trade-offs

| Decision | Alternative considered | Why we chose this |
|---|---|---|
| One global limit (`BOOKING_QUOTA_LIMIT`, default 12) | Per-user `booking_quota` column with a migration | The brief specifies one configurable limit. No migration, and no admin interface is needed. |
| Count with a query at request time | Stored counter updated on create and cancel | Always consistent with the stored bookings. A stored counter can't drop bookings when their start time passes without a scheduler. |
| Reject if `count + n > limit` | Accept if `count < limit` | The second ignores series size: 10 + a series of 3 would be accepted, but the brief requires rejection. |
| Quota checked after all core checks, before any insert | Check while inserting each occurrence | Keeps all-or-nothing trivially true and leaves the existing error messages unchanged (conflict before quota). |
| `quota_limit` argument overrides the environment | Environment only | Tests can use small limits (the brief allows this) without changing the process environment. |

**Cost of the chosen design:** one extra `COUNT` query per create request, and
no way to give different users different limits.

## 4. Known limitations

- **Simultaneous requests can exceed the limit** (check-then-insert race, like
  the core's C11). Possible mitigations: `BEGIN IMMEDIATE` on SQLite, or a
  per-user lock. Not implemented; out of scope.
- **Single bookings are limited** as our interpretation of the brief, which
  only states the series rule. A question was sent to the instructor.
- **The base core does not match Appendix A** (`/booking-series`,
  `GET /series/{booking_id}`, `?future=true`). The extension is built on the
  core as the team merged it.
- **There is no way to see remaining quota** without trying a booking. There is
  no quota endpoint, by design.
- **Changing the limit needs a restart**, since it's read once at start-up.
