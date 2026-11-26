# Extension verification: per-user booking quotas

Plan and test IDs (Q1–Q10, QT1–QT19): [`extension-plan.md`](extension-plan.md).
Quota tests: [`tests/test_quota_extended.py`](../tests/test_quota_extended.py).
Core regression tests: `tests/test_bookings.py`, `test_cancellation.py`,
`test_resources.py`, `test_series.py`.

## 1. Commands

From the project directory, with the virtual environment activated
(PowerShell: use `.venv\Scripts\python.exe` instead of `python`):

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy booking
```

## 2. Recorded results

### 2a. Submission run

<!-- SUBMISSION-RUN: replace this comment with the real output of the four
     commands above, plus `python --version` and `git rev-parse --short HEAD`,
     run on the final commit just before building the ZIP. -->

### 2b. History of runs, including failures

| When / commit | `pytest` | `ruff check` | `ruff format --check` | `mypy booking` |
|---|---|---|---|---|
| **Baseline**: core before the extension, `2f9b4e3` | 88 passed | **Failed: 3 errors** (long lines) | **Failed: 3 files** would be reformatted | Success |
| `main` after merging #15, #17, #18 (`7ade866`) | 118 passed | **Failed: 2 errors** (E501 in `booking/database.py:28` and `booking/main.py:124`) | **Failed: 4 files** would be reformatted | Success |
| After the formatting fix (`c9e2e2a`) and the quota-helper tidy-up | 118 passed | All checks passed | 13 files already formatted | Success |

Runs in 2b were recorded on 2026-11-26 (Linux, Python 3.13). The ruff failures
were pre-existing in the core. They were fixed by formatting only (`c9e2e2a`),
with no behaviour change: the same 118 tests pass before and after.

## 3. What the tests establish

Every quota test uses an isolated SQLite file, a controllable clock and, where
useful, a small `quota_limit`. Rejection cases use `assert_quota_rejection`,
which checks the **409 status, the `"Booking quota exceeded"` detail, and that
`GET /bookings` is unchanged**. So "nothing was stored" is verified, not assumed.

| Plan ID | Property | Test(s) in `tests/test_quota_extended.py` |
|---|---|---|
| QT1, QT2 | 10 existing + series of 2 → 201 (reaches 12); + series of 3 → 409, still 10, no rows added (brief example) | `test_series_remaining_quota` (parametrized) |
| QT3 | Series exactly fills the quota | `test_series_fills_entire_quota`, `test_series_fits_exactly_or_is_rejected_atomically` |
| QT4 | Single booking rejected when full; quota counts across resources (full on resource 1, rejected on resource 2) | `test_single_booking_rejected_at_quota` |
| QT5 | Series of 1 rejected when full; nothing stored | `test_series_rejected_at_quota` |
| QT6, QT7, QT17 | Bookings starting exactly now, ongoing and past ones do not count | `test_started_bookings_do_not_count_towards_quota` (parametrized) |
| QT8 | Cancelling a single booking frees a place | `test_single_cancellation_releases_quota`, `test_quota_counts_occurrences_and_releases_capacity` |
| QT9 | Series cancellation (`?future=true`) frees all places; replacement series gets a new series ID | `test_series_cancellation_releases_quota` |
| QT10 | Quota is per user | `test_quota_is_independent_for_each_user` |
| QT11 | Conflict error takes precedence over the quota error; nothing stored | `test_series_conflict_checked_before_quota` |
| QT12 | Default limit is 12 (env unset): 12 accepted, 13th rejected | `test_default_quota_is_twelve` |
| QT15 | Invalid limits (0, −1, `abc`, explicit 0/−1/non-integer) refused at start-up | `test_invalid_environment_quota`, `test_invalid_explicit_quota`, `test_quota_configuration` |
| QT16 | `quota_limit` overrides `BOOKING_QUOTA_LIMIT` | `test_explicit_quota_overrides_environment`, `test_override_takes_precedence` |
| QT18 | Limit from `BOOKING_QUOTA_LIMIT` is enforced | `test_environment_quota_enforced`, `test_quota_configuration` |
| QT19 | Intended change: the 13th booking is rejected after the extension | `test_extension_rejects_booking_above_default_quota` (single and series) |
| QT13 | **Core regression**: the 88 baseline core tests still pass at the default limit | full `python -m pytest`; core test assertions unchanged (only reformatted, plus one new overflow test, see `extension-design.md` §2) |
| QT14 | Lint, format, types | the four commands in §1 |

### QT19 baseline vs extension (recorded)
Same scenario at both commits: user 1 holds 12 future bookings, then requests a
13th (as a single booking, and separately as a one-occurrence series), with
`BOOKING_QUOTA_LIMIT` unset.

```text
baseline-2f9b4e3 single 13th booking -> 201  | stored for user 1: 13
baseline-2f9b4e3 series 13th booking -> 201  | stored for user 1: 13
extension        single 13th booking -> 409 {'detail': 'Booking quota exceeded'} | stored for user 1: 12
extension        series 13th booking -> 409 {'detail': 'Booking quota exceeded'} | stored for user 1: 12
```

This is the **intended** rule change (Q8), not a regression. No baseline core
test creates more than 12 future bookings for one user, so none is affected.

### Mutation check: do the quota tests detect real bugs?
Each bug below was planted in `booking/main.py` one at a time, and
`tests/test_quota_extended.py` was re-run (Claude-assisted check, 2026-11-26).

| Planted bug | Result |
|---|---|
| Count `start >= now` (a booking starting now still counts) | caught (2 tests fail) |
| Count by `end > now` (ongoing bookings count) | caught (3) |
| Cancelled bookings still count | caught (3) |
| Count every user's bookings | caught (2) |
| Off by one (`>= limit`) | caught (17) |
| A series counts as 1 instead of n | caught (4) |
| Single bookings not checked | caught (6) |
| Default limit 13 | caught (4) |
| `BOOKING_QUOTA_LIMIT` ignored | caught (5) |
| Environment wins over `quota_limit` | caught (3) |
| Quota checked before the conflict check | caught (1) |
| First occurrence saved before the quota check (partial series) | caught (10) |
| A limit of 0 accepted | caught (2) |

All 13 were caught. An independent set of 19 quota tests (from PR #14) also
passes on the final code.

## 4. What is not checked

- **Simultaneous requests.** Two concurrent requests can read the same count
  and both be accepted, ending above the limit (the same check-then-insert race
  as the core's C11). Not prevented; only sequential behaviour is guaranteed.
- **Single bookings being limited** is our interpretation. The brief only states
  how series are accepted. A question was sent to the instructor.
- **Base core vs Appendix A.** The extension sits on the team-merged core
  (`/booking-series`, `?future=true`), which doesn't match Appendix A; quota
  behaviour through Appendix A routes isn't available or tested.
- **DST transitions**: out of scope.
- **Real server and clock.** Tests use `TestClient` and a fake clock. The README
  shows how to run the server with `BOOKING_QUOTA_LIMIT`.
- `ruff` and `mypy` check style and types, not behaviour. There is no coverage target.
