# Retrospective (Team 16): working core and quota extension

## What worked
- **Planning the extension before coding.** The quota plan (PR #13, first
  committed 2026-11-23) listed requirements, assumptions, risks and 19 numbered
  test cases before any extension code was written. The tests in
  `tests/test_quota_extended.py` are labelled with those QT numbers, so every
  requirement can be traced to a test.
- **A simple, derived design.** The quota is calculated from existing booking
  records, so there was no schema migration and no second counter that could
  become stale. Cancellation and time passing are handled automatically.
- **Reproducible time boundaries.** Tests use an injected clock, which makes the
  strict `start > now` rule (exactly-now, ongoing and past bookings) testable.
- **Testing stored state, not just status codes.** Series validation and
  conflict checks run before the quota check and before any insert, and
  rejection tests check that `GET /bookings` is unchanged after a 409. A
  mutation check on the final code showed the quota tests catch all 13 planted
  bugs, including a partial series.
- **Design discussed in review.** A teammate's review proposed a hard-coded
  limit and questioned whether the quota needed a database column. Talking it
  through confirmed the design: no schema change, one count query, and
  `count + n > limit` rather than `count < 12` (which would wrongly accept
  10 + 3).
- **Recording the intended change explicitly.** Running the same "13th
  booking" scenario at the baseline (201) and after the extension (409) made it
  clear that this difference is the new rule, not a regression.

## What caused difficulty
- **Work split vs. what was built.** The plan gave the configuration and count
  helper to one person and the series check to another. Both wrote their own
  configuration and count code, and merging branches meant resolving
  overlapping edits in `booking/main.py`. The two versions ended up side by
  side; tests still passed, which hid the duplication, so it had to be found by
  reading the code and consolidated afterwards.
- **Overlapping and stale pull requests.** Several PRs implemented the same
  thing (#14, #15, #16), and some stayed open after their code reached `main`
  through other commits, so it was hard to tell what was actually merged.
- **Lint failures carried over.** Ruff errors from the core (long lines, import
  order, a test-file docstring placement) persisted until the last day.
  Formatting did not fix every lint error at once; changed files had to be
  re-checked after each edit.
- **A tracked database file.** Running the app and tests modified the tracked
  `booking.sqlite3`, so we had to stage only intended files instead of using
  `git add .`. It is now untracked and in `.gitignore`.
- **Plan vs. published contract (working core).** Our change plan used its own
  API (`/booking-series`, `?future=true`), which differs from Appendix A. This
  wasn't caught before coding, so the core still doesn't match Appendix A, and
  the extension inherits that.
- **Tests edited to fit the code (working core).** Contract tests were changed
  to match the implementation three times (`6a65b4f`, `5d8592f`, `2d9feb7`),
  which hid spec mismatches instead of fixing them.
- **Late integration and packaging.** Both milestones were integrated on the
  deadline day. The first working-core ZIP included `.git`, `.venv` and
  databases, and its index cited files that weren't in the ZIP.
- **One global limit** gives independent counts per user, but can't give
  different users different limits.

## What we would change next time
1. **Check the plan against the published interface first**, endpoint by
   endpoint, before anyone writes code.
2. **Agree on shared pieces before splitting work**: the helper signature, the
   environment variable name, the error response and the validation order.
   **One owner per shared function**; others call it, they don't re-implement it.
3. **Integrate smaller commits earlier**, so conflicts in shared files appear
   before implementation and tests are finished.
4. **Run pytest, ruff check, ruff format --check and mypy after every
   integration**, keep `main` green, and record the exact commands and results
   as we go, instead of reconstructing them at the end.
5. **Record the baseline before implementation**, then compare the same suite
   after, separating intended rule changes from regressions.
6. **A failing contract test means check the spec.** Tests change only when the
   spec says so, with the reason recorded in the PR.
7. **Keep test and runtime databases out of the repository.**
8. **Close or update PRs as soon as their code lands elsewhere.** Build the ZIP
   with `git archive`, and check the evidence index against the extracted ZIP
   before uploading.

## Who did what (extension)

| Member | Contribution | Evidence |
|---|---|---|
| Saniya Shaikh | Pre-implementation plan (with David); README quota section, verification record, design notes, retrospective; quota-helper consolidation and mutation check (Claude-assisted) | PR #13, final-docs PR |
| Matan David | Plan review and editing (hard-code vs configurable discussion); ruff formatting fix; integration and merges; draft evidence and retrospective notes | `c9e2e2a`, merges of #15, #17, #18 |
| Sean Rodriguez | Quota configuration and count helpers; single-booking quota check | PR #15 (`c0379a5`) |
| Sean Huang | Series quota check, configuration validation, overflow handling, original quota tests and README draft | PR #16 (`b91b5b7`), brought into `main` via `0da91c1` |
| Jaden Rajan George | QT-labelled quota acceptance and regression tests; integration of the series quota code | PRs #17, #18 (`0967666`, `693fccb`, `0da91c1`) |
