# Extension plan: per-user booking quotas (Team 16)

**Status: pre-implementation plan.** Committed before any extension code. Later
changes are recorded in §9, not by editing the earlier sections.

Selected extension: **2. Per-user booking quotas.**
Base: the working core on `main` at `2f9b4e3`, as the team merged it (change-plan
API: `POST /booking-series`, `GET /series/{booking_id}`,
`POST /bookings/{id}/cancel?future=true`). This core does not match Appendix A
(see the working-core verification and PR #10). That is recorded as a known
limitation and is not changed by this extension.

## 1. Requirements (testable restatement)

| ID | Requirement (from the extension brief) |
|---|---|
| Q1 | A configurable limit, **default 12**, of confirmed future occurrences **per user**, counted **across all resources**. |
| Q2 | Each occurrence counts separately: every series occurrence **and every single booking**. |
| Q3 | An occurrence counts only while its **start is strictly later than now**. Starting exactly now, ongoing and past occurrences do not count. |
| Q4 | Only **confirmed** (uncancelled) bookings count. Cancelling an occurrence or single booking releases its place. |
| Q5 | A new series is accepted only if **every** occurrence fits in the remaining quota **and** the ordinary core checks pass. |
| Q6 | If a series would exceed the limit, **reject the whole series and create no bookings** (all-or-nothing, as in C5). |
| Q7 | Tests may use a smaller limit. |
| Q8 | All core behaviour (C1–C12) is preserved, except where Q1–Q7 change a rule. |

Brief example: a user with 10 confirmed future occurrences can book 2 more
(reaching exactly 12). Requesting 3 fails, and the count stays at 10.

## 2. Assumptions and open questions

| # | Open detail | Our assumption | Reason | Question for instructor |
|---|---|---|---|---|
| A1 | Does the quota also **reject single bookings** at the limit? The brief only says how series are accepted. | **Yes.** `POST /bookings` is rejected if it would make the count exceed the limit. | Q1 is a per-user limit and Q2 counts single bookings. If singles bypassed it, users could hold more than 12, which defeats the limit. | "Should a single booking be rejected when the user already has 12 confirmed future occurrences?" |
| A2 | Status code for exceeding the quota | **409** with `{"detail": "Booking quota exceeded"}` | Same as the core's state-dependent rejection (conflict). The request is well-formed, so 422 is wrong; the user is allowed to book, so 403 is wrong. | Covered by the same email. |
| A3 | Precedence when a request both conflicts and exceeds the quota | Core order is unchanged: shape (422) → user/resource (404) → time rules (422) → slot conflict (409) → **quota (409)** | Keeps every existing error exactly as before (Q8). Quota is a new last gate. | None. No precedence among simultaneous errors is specified. |
| A4 | How it's configured | `create_app(..., quota_limit=12)`. The server reads env `BOOKING_QUOTA_LIMIT` (default 12). | Tests pass a small limit (Q7) through the existing factory, the same pattern as `clock=`. No HTTP endpoint changes it, matching the core's no-admin-interface rule. | None |
| A5 | Is the count shown to the client? | **No new endpoint.** | Not required. Less surface means less risk. Verified through behaviour and `GET /bookings`. | None |
| A6 | Count when the clock moves | Computed **at request time** from stored bookings | No stored counter can drift; past and ongoing occurrences drop out automatically (Q3). | None |

## 3. Change-impact analysis

**Affected core requirements**
- C1/C5 (series creation): gains a new all-or-nothing rejection reason.
- C10 (single bookings): gains a new rejection (A1).
- C7–C9 (cancellation): unchanged code, but now **frees quota**, which must be tested.
- C3, C4, C6, C11, C12: unchanged.

**Affected code** (`booking/main.py` on the chosen base)
| Element | Change |
|---|---|
| `create_app(database, *, clock)` | Add `quota_limit: int \| None = None`; resolve from env, default 12, must be ≥ 1 |
| New helper `future_booking_count(session, owner_id, now) -> int` | `COUNT(*) WHERE owner_id = ? AND cancelled = false AND start > now` |
| Series creation handler `create_booking_series` (`POST /booking-series`) | After all occurrences pass the core checks, and **before any `session.add`**: reject 409 if `count + n > limit` |
| `create_booking` | Same check with `n = 1` (A1) |
| `cancel_booking` (incl. `?future=true`), `get_series`, reads | **No change** (release is automatic because the count reads `cancelled = false`) |

**Data model:** no change. There's no per-user column and no migration. The
count is derived from `Booking`.
**Interfaces:** request and response shapes are unchanged. One new error
response (409, `Booking quota exceeded`) on the two creation endpoints. One new
configuration input (`quota_limit` / `BOOKING_QUOTA_LIMIT`).
**Docs:** README gets a quota section and the env var; the error table gets the new 409.

## 4. Design alternatives

| Decision | Options considered | Choice and reason |
|---|---|---|
| Where the limit lives | (a) **one global configurable limit**; (b) a per-user `booking_quota` column with a migration (an earlier local prototype by Sean H did this, with default 3) | **(a).** The brief specifies one configurable limit of 12, not per-user limits. (b) needs a schema migration, has no admin interface to set it, and its default of 3 would break C1 (series of up to 12). |
| How the count is kept | (a) **query at request time**; (b) a stored counter on the user, updated on create and cancel | **(a).** (b) must also handle time passing (occurrences stop counting at their start), which a stored counter can't do without a scheduler. (a) is always consistent with the stored bookings. |
| Where the check runs | (a) **after all core checks, before any insert, in the same session**; (b) per occurrence while inserting | **(a).** Keeps all-or-nothing (Q6/C5) trivially true, because nothing is added unless every check passes. (b) risks partial series. |
| Single bookings | (a) **enforce** (A1); (b) series only | **(a).** See A1. Documented as an assumption, with a question sent. |
| Visibility | (a) **no endpoint**; (b) `GET /me/quota` (prototype) | **(a).** Not required. Fewer interfaces to test and keep stable. |

## 5. Risks and dependencies

| Risk | Mitigation |
|---|---|
| Base core differs from Appendix A (main fails 58/64 Appendix A tests; ruff fails) | Building on main as merged. Listed as a known limitation; the pre-existing ruff errors are fixed in this extension. |
| Boundary errors (`>=` vs `>`) at `start == now` | Dedicated boundary tests with the controlled clock |
| Partial series on quota failure | Check before any `session.add`; test stored state, not just the status code |
| Existing core tests exceed the limit for one user | Run the full suite at the default 12; core tests create at most 12 per user per test |
| Simultaneous requests can both pass the count | Same check-then-insert race as C11. Documented as a limitation, not prevented. |
| Tests edited to fit the code (happened 3× in the core) | Tests follow this plan and the brief. A failing test means fix the code or record a justified assumption change in §9. |

## 6. Verification plan (expected results)

All tests use `create_app(database=tmp, clock=Clock, quota_limit=N)`. Every
rejection test also checks that `GET /bookings` is unchanged.

| Test ID | Setup → action | Expected | Req. |
|---|---|---|---|
| QT1 | limit 12; user has 10 future → series of 2 | 201; 12 future | Q1, Q5 (brief example) |
| QT2 | limit 12; user has 10 future → series of 3 | 409; **no new rows**; still 10 | Q5, Q6 (brief example) |
| QT3 | limit 3; series of 3 | 201 (exactly at the limit) | Q5 |
| QT4 | limit 3; 3 future across **two resources** → single booking on a third | 409 | Q1, A1 |
| QT5 | limit 2; 2 singles → series of 1 | 409; nothing stored | Q2 |
| QT6 | limit 1; booking starts at T; clock = T → new booking | 201 (start == now doesn't count) | Q3 |
| QT7 | limit 1; clock inside an ongoing booking → new booking | 201 | Q3 |
| QT8 | limit 1; booking cancelled → new booking | 201 | Q4 |
| QT9 | limit 3; series of 3; series cancel (`?future=true`) → new series of 3 | 201 | Q4 |
| QT10 | limit 2; user 1 at limit → user 2 books | 201 (per user) | Q1 |
| QT11 | limit 3; series of 6 where occurrence 6 **also conflicts** | 409 with the **conflict** message (A3 order) | A3 |
| QT12 | default limit (no argument, env unset) | 12 accepted, 13th rejected | Q1, A4 |
| QT13 | Full core suite at the default limit | all pass, unchanged | Q8 |
| QT14 | `ruff check`, `ruff format --check`, `mypy booking` | clean | — |

Recorded in `docs/verification.md` with the real commands and output, including failures.

## 7. Work allocation and integration order

1. **This plan** → PR → approve → merge (before any extension code).
2. **Implementation** (Sean H; Jaden reviews): config, helper, two checks.
3. **Tests QT1–QT12** (Saniya; Sean R reviews), written from this plan, in parallel with step 2.
4. **Docs** (Saniya + David): README quota section, verification, design changes, limitations, retrospective.
5. **Integration** (David): merge 2 → 3 → 4 via reviewed PRs; run all checks; record results.
6. **Submission** (Saniya + David): `git archive` ZIP; index with links pinned to the submitted commit.

## 8. Out of scope
Per-user limits, a quota-management interface, a quota read endpoint,
concurrent-request guarantees, and DST.

## 9. Changes after implementation
_(Filled in after implementation: what changed from this plan, and why.)_
