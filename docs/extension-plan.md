# Extension Plan: Per-user Booking Quotas

**Course:** CPS731 Software Engineering I
**Team:** 16
**Base:** Team-merged core on `main` at `2f9b4e3`, including `POST /booking-series`, `GET /series/{booking_id}`, and `POST /bookings/{booking_id}/cancel?future=true`.

| Member | Student number |
|---|---|
| Saniya Shaikh | 501275613 |
| David Matan | 501130510 |
| Sean Rodriguez | 501257532 |
| Sean Huang | |
| Jaden Rajan George | 501131321 |

## 1. Requirements

| ID | Requirement | Description |
|---|---|---|
| Q1 | Booking limit | Each user can have a maximum of 12 active future bookings. The limit is configurable and applies across all resources. |
| Q2 | Series counting | Every occurrence in a booking series counts as one booking. |
| Q3 | Future bookings | Only uncancelled bookings with a start time later than the current time count toward the limit. |
| Q4 | Cancellation | Cancelling a booking or series occurrence immediately frees up quota. |
| Q5 | Booking validation | A booking or series is accepted only if it passes the existing core validations and stays within the user's quota. |
| Q6 | Series rejection | If a series exceeds the remaining quota, the entire request is rejected. No occurrences are created. |
| Q7 | Configurable testing | Tests can specify a quota different from the default limit. |
| Q8 | Core compatibility | Existing core requirements C1–C12 remain unchanged, except for the additional quota rejection condition. |
| Q9 | Sequential requests | A user's active future booking count must never exceed the configured limit when requests are processed sequentially. |
| Q10 | Configuration validation | The configured quota must be a positive integer. |

Example: A user with 10 active future occurrences can add two and reach the default limit of 12. A request for three is rejected, leaving the existing 10 unchanged.

## 2. Assumptions and rules

| Area | Decision | Explanation |
|---|---|---|
| Quota scope | Global limit | Every user has the same maximum, regardless of which resources they book. |
| Default quota | 12 bookings | The system allows 12 active future bookings per user unless configured otherwise. |
| Configuration | In `main.py` add `BOOKING_QUOTA_LIMIT` | The environment variable controls the default limit. |
| Test override | `quota_limit=N` | Tests can override the environment setting when creating the application. |
| Invalid configuration | In `main.py` Raise `ValueError` | The application must reject zero, negative, or non-integer quota values before handling requests. |
| Booking count | Count database rows | Each uncancelled future occurrence belonging to the user counts as one booking. |
| Time comparison | `start > now` | Bookings starting exactly now, already in progress, or in the past are excluded. |
| Time source | Injected clock | The same current-time value is used for both core validation and quota calculation within a request. |
| Cancellation | Derived automatically | No separate quota counter is required. Cancelling a booking removes it from the count. |
| Validation order | Core checks first | Identity, resource, timestamp, duration, and conflict checks run before quota validation. |
| Series creation | All-or-nothing | Every occurrence is validated before insertion. If quota is exceeded, none are inserted. |
| Concurrency | Sequential requests only | Simultaneous requests may exceed the limit because both could pass the count check before either inserts its booking. |
| Database changes | None | The quota is calculated from existing booking records. No migration or additional user column is required. |

## 3. Design and Implementation

### Quota calculation

| Item | Description |
|---|---|
| Helper | `main.py/future_booking_count(session, owner_id, now)` |
| Purpose | Calculate how many bookings currently count toward a user's quota. |
| Conditions | The booking belongs to the user, is not cancelled, and starts after the current time. |
| Result | Return the total number of matching booking records. |

### Endpoint behaviour

| Endpoint | When to check quota | If the quota is exceeded |
|---|---|---|
| `main.py/ POST /bookings` | After all existing validations and conflict checks, but before inserting the booking. | Return HTTP 409 with `{"detail":"Booking quota exceeded"}`. Do not create a booking. |
| `main.py/ POST /booking-series` | After validating every occurrence and checking all conflicts, but before inserting any occurrence. | Return HTTP 409 with `{"detail":"Booking quota exceeded"}`. Do not create any series occurrences. |
| Cancellation endpoints | No additional quota check is needed. | Existing cancellation behaviour remains unchanged. The cancelled booking automatically stops counting. |
| Read endpoints | No quota check is needed. | Existing responses remain unchanged. |

**API compatibility:** Both creation endpoints retain their existing request and successful response formats. The only new API response is the quota-exceeded HTTP 409 error.

### Design alternatives

We considered a global environment variable and a per-user quota column. The requirements do not specify whether quotas can differ by user, so we assume one global quota. We selected the environment variable because it avoids a database migration. A per-user column would support different limits but require schema changes and quota management. Revisit this decision if user-specific limits are needed.

| Design consideration | Global environment variable (selected) | Per-user database column (not selected) |
|---|---|---|
| Quota amount | Same for every user | Can differ between users |
| Configuration | Environment variable | Database record |
| Changing the limit | Update configuration and restart/reload | Update the user's database record |
| Database migration | Not required | Required |
| Implementation complexity | Low | Higher |
| Best suited for | One system-wide booking limit | Different limits for different users or roles |

Also, we derive the active-future count from booking records instead of storing a separate count. Cancellation and the passage of time both change which bookings qualify; a stored counter would need reliable updates for both to avoid becoming stale.

## 4. Change impact

| Existing core feature | Expected impact |
|---|---|
| C1/C5 – Series creation | Add quota validation. Preserve the existing all-or-nothing creation behaviour. |
| C10 – Single bookings | Add quota validation before inserting a booking. |
| C7–C9 – Cancellation | No changes to cancellation logic. Cancelled bookings automatically free quota. |
| C3, C4, C6, C11, C12 | No intended changes to existing behaviour. |
| Database models | No changes required. |
| Database migrations | No migrations required. |

## 5. Risks and dependencies

| Risk or dependency | How it will be handled |
|---|---|
| Existing tests or lint checks may already fail. | Run the complete baseline suite at `2f9b4e3` before implementation. Record the commands and results, and distinguish existing failures from new regressions. |
| Incorrect handling of bookings starting exactly now. | Use a fixed injected clock and test past, ongoing, and exactly-now bookings separately. |
| Partial series creation after quota rejection. | Check quota before inserting any occurrences. Verify that the database remains unchanged after rejection. |
| Both a conflict and quota violation occur in the same request. | Run core validation first. The ordinary conflict error must take precedence over the quota error. |
| Invalid or inconsistent quota configuration. | Use only `BOOKING_QUOTA_LIMIT` and `quota_limit`. Test defaults, overrides, and invalid values. |
| Existing tests reach the default quota unintentionally. | Use isolated databases and review test setup. Do not increase the default limit just to make tests pass. |
| Simultaneous requests exceed the quota. | Document the concurrency limitation. Preventing this race is outside the scope of this extension. |
| Existing tests or workflows may be rejected when a user already has 12 active future bookings. | Review existing test data and workflows for cases that exceed the quota. Use a higher `quota_limit` for tests covering unrelated behavior. For tests that intentionally exceed the limit, expect `409 Booking quota exceeded` and verify that no booking was added. Document these as intended changes to booking behavior. |

## 6. Verification plan

### Test setup and pass criteria

All tests will use:

- Pytest and the application test client.
- A separate temporary SQLite database for each test.
- Seeded users and resources.
- A controllable clock to test booking time boundaries.
- All booking requests in these tests are sent sequentially. Each request completes before the next begins.
- Non-overlapping fixture bookings unless a test specifically checks conflicts.

For every rejected request, verify:

1. The correct HTTP status is returned.
2. The response contains the expected error detail.
3. No unintended database rows are inserted.
4. Existing bookings remain unchanged.

For successful requests, verify the inserted rows, timestamps, ownership, resource assignments, series IDs, and cancellation status.

### Quota test cases

| Test | Scenario and action | Expected result | Trace |
|---|---|---|---|
| QT1 – Series reaches limit | Set the limit to 12. Give a user 10 active future bookings, then create a series of 2. | 201 Created. Two occurrences are inserted under the same series ID. The user's total becomes 12. | Q1, Q2, Q5, Q9 |
| QT2 – Series exceeds limit | Set the limit to 12. Give a user 10 active future bookings, then create a series of 3. | 409 Conflict. The series is rejected. No new rows are inserted, and the original 10 bookings remain unchanged. | Q1, Q5, Q6, Q9 |
| QT3 – Series exactly fills quota | Set the limit to 3. Create a series containing 3 occurrences for a user with no existing bookings. | 201 Created. All 3 occurrences are inserted under one series ID. | Q1, Q2, Q5, Q7, Q9 |
| QT4 – Quota applies across resources | Set the limit to 3. Give a user 3 active future bookings on resource 1. Request a valid booking on resource 2. | 409 Conflict. The request is rejected because the quota applies across all resources. No new row is inserted. | Q1, Q5, Q9 |
| QT5 – Single occurrence exceeds quota | Set the limit to 2. Give a user 2 active future bookings. Request a series containing 1 occurrence. | 409 Conflict. The series is rejected. No series or occurrence is inserted. | Q2, Q5, Q6, Q9 |
| QT6 – Booking starts exactly now | Set the limit to 1. Give a user an existing booking starting at time T. Set the clock to T and request another valid booking for the same resource starting after the existing booking ends. | 201 Created. The existing booking does not count because its start time equals the current time. | Q3, Q5 |
| QT7 – Ongoing booking | Set the limit to 1. Give a user a booking running from 10:00 to 12:00. Set the clock to 11:00 and request another valid booking for the same resource starting after the existing booking ends. | 201 Created. The ongoing booking does not count toward the quota. | Q3, Q5 |
| QT8 – Cancelling a single booking | Set the limit to 1. Give a user one active future booking. Cancel it, then request a replacement. | 201 Created. Cancellation succeeds, the original row remains marked as cancelled, and the replacement is accepted. | Q4, Q5 |
| QT9 – Cancelling a series | Set the limit to 3. Create a series of 3 future occurrences. Cancel the series using `future=true`, then create a replacement series of 3. | 201 Created. The replacement series is accepted. Original rows remain cancelled, and the new series has a different series ID. | Q2, Q4, Q5 |
| QT10 – Quotas are independent per user | Set the limit to 2. Give user 1 two active future bookings. Have user 2 create a valid booking. | 201 Created. User 2's booking is accepted. User 1's bookings remain unchanged. | Q1, Q9 |
| QT11 – Conflict takes precedence over quota | Set the limit to 3. Request a series of 6. Make the first 5 occurrences conflict-free and the sixth conflict with an existing booking. | 409 Conflict. The ordinary resource-conflict error is returned, not the quota error. No new occurrences are inserted. | Q5, Q6, Q8 |
| QT12 – Default quota | Leave `BOOKING_QUOTA_LIMIT` unset and do not provide a test override. Create 12 valid future bookings, then request a 13th. | First 12 requests return 201. The 13th returns 409 with the quota error. Exactly 12 active future bookings remain. | Q1, Q9 |
| QT13 – Core regression tests | Run the unchanged core test suite at baseline commit `2f9b4e3` and again after the extension, using the default quota of 12. | Compare results by test. All tests that do not exceed the new quota must retain their baseline results. If an unchanged baseline test expects 201 for a booking request that exceeds the quota, record the extension's `409 Booking quota exceeded` as an intended behavior change, not an unrelated regression. Verify that no booking is added. Use QT19 to explicitly test this behavior. Report baseline and extension test outcomes, plus Ruff and formatting results, separately. | Q8 |
| QT14 – Code quality checks | Run `ruff check`, `ruff format --check`, and `mypy booking`. Compare results against the baseline. | No new lint, formatting, or type errors are introduced. Existing failures are documented separately. | — |
| QT15 – Invalid quota values | Test invalid values through both configuration sources. With no `quota_limit` override, set `BOOKING_QUOTA_LIMIT` to `0`, `-1`, and `abc` in separate cases. In separate cases, pass `quota_limit=0`, `quota_limit=-1`, and a non-integer value. | `create_app` raises a clear `ValueError` before handling requests. No booking data is changed. | Q10 |
| QT16 – Test override precedence | Set `BOOKING_QUOTA_LIMIT=5` and create the application with `quota_limit=2`. Attempt to create 3 valid future bookings. | The first 2 are accepted. The third is rejected with 409, confirming that the explicit override takes precedence. | Q7, Q10 |
| QT17 – Past booking excluded | Set the limit to 1. Seed an uncancelled booking that ended before the fixed clock time. Request a valid future booking on another resource. | 201 Created. The past booking does not count toward quota, and the new booking is stored. | Q3, Q5 |
| QT18 – Environment-configured quota | Set `BOOKING_QUOTA_LIMIT=5` and do not provide a `quota_limit` override. Create five valid, non-overlapping future bookings for one user, then request a sixth. | The first five requests return 201. The sixth returns 409 with `{"detail":"Booking quota exceeded"}`. Exactly five active future bookings remain. | Q1, Q7, Q9, Q10 |
| QT19 – Intended change from baseline | Run the same two scenarios with isolated databases at baseline commit `2f9b4e3` and after the extension. In each scenario, seed 12 valid, non-overlapping future bookings for one user; request either a single booking or a one-occurrence series that would bring the total to 13. | Baseline: both requests return 201. Extension: both return 409 with `{"detail":"Booking quota exceeded"}`. No new rows are added, and the original 12 remain unchanged. Record the two baseline-versus-extension results. | Q1, Q5, Q6, Q8, Q9 |

## 7. Work Allocation and Integration Order

| Order | Owner | Deliverable | Dependency / Review |
|---|---|---|---|
| 1. Confirm baseline and design | David Matan, Saniya Shaikh | Record baseline results and finalize quota configuration, error response, and validation order. | Team approval before implementation begins. |
| 2. Implement quota configuration and single-booking enforcement | Sean Rodriguez | Add quota configuration, validation, the shared quota-count helper, and quota enforcement for `POST /bookings`. | Coordinate the shared helper and configuration with Sean Huang. David Matan reviews the implementation. |
| 3. Implement series quota enforcement | Sean Huang | Add the all-or-nothing quota check to `POST /booking-series`, after core validation and before inserting any occurrences. | Depends on the shared helper and configuration. David Matan reviews the implementation. |
| 4. Create tests and update documentation | Jaden Rajan George – tests; Saniya Shaikh – documentation | Jaden implements quota and regression tests. Saniya updates the README and verification record. | Confirm expected behaviour with Sean Rodriguez and Sean Huang. |
| 5. Integrate and review | David Matan, whole team | Integrate reviewed changes, run checks, compare results with the baseline, and record final outcomes. | The team reviews the integrated implementation before submission. |

## 8. Evidence and Submission Check List

| Evidence | Required Record |
|---|---|
| Base and implementation state | Base commit `2f9b4e3`, final commit or pull request link, and branch name. |
| Baseline and final checks | Commands executed, pass/fail results, and a clear distinction between pre-existing failures and new regressions. |
| Quota behaviour | Results for QT1–QT19, including database assertions confirming that rejected requests do not modify existing bookings or insert new rows. |
| Configuration | Default quota, environment variable, test override, configuration precedence, and invalid-value results. |
| Documentation | Updated README documenting quota configuration and the quota-exceeded error response. |
