# Campus resource booking starter
[![Lint status](https://github.com/miranska/cps-731-campus-booking/actions/workflows/lint-status.yml/badge.svg?branch=main&event=workflow_run)](https://github.com/miranska/cps-731-campus-booking/actions/workflows/ci.yml?query=branch%3Amain)
[![Test status](https://github.com/miranska/cps-731-campus-booking/actions/workflows/test-status.yml/badge.svg?branch=main&event=workflow_run)](https://github.com/miranska/cps-731-campus-booking/actions/workflows/ci.yml?query=branch%3Amain)
[![Coverage](https://github.com/miranska/cps-731-campus-booking/raw/python-coverage-comment-action-data/badge.svg)](https://github.com/miranska/cps-731-campus-booking/tree/python-coverage-comment-action-data)
[![Python 3.14](https://img.shields.io/badge/python-3.14-blue?logo=python&logoColor=white)](https://www.python.org/downloads/)

This is a **course simulation of an existing system**, created for CPS731.
Browse resources and create, retrieve, list and cancel persistent single bookings,
or create persistent weekly booking series.

## Run locally

Supported Python: **3.14** (standard CPython). Install it from
[python.org](https://www.python.org/downloads/) before starting. Run all commands
from this directory; no files from the surrounding course repository are needed.

macOS/Linux:

```sh
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m booking.database init
python -m uvicorn booking.main:create_app --factory --host 127.0.0.1 --port 8000
```

Windows PowerShell: create the environment with `py -3.14 -m venv .venv`.
Then use `.venv\Scripts\python.exe` in place of `python` in the commands above
and below; activation is unnecessary.

Open [interactive API docs](http://127.0.0.1:8000/docs), expand `GET /resources`,
choose **Try it out**, then **Execute**. The JSON API schema is at
[/openapi.json](http://127.0.0.1:8000/openapi.json).
The docs page loads Swagger UI assets from a CDN, so that page needs internet;
the API itself works locally without internet after dependency installation.
Stop the server with Ctrl+C.

## Data and reset

The SQLite file defaults to `booking.sqlite3` in your current directory.
Both the server and initialization command honor `BOOKING_DATABASE`, a filesystem
path (not a database URL). For example, in macOS/Linux:

```sh
export BOOKING_DATABASE=/tmp/my-booking.sqlite3
python -m booking.database init
```

In PowerShell: `$env:BOOKING_DATABASE = "$env:TEMP\my-booking.sqlite3"`.
Use the same setting and working directory for initialization and the server.

`init` creates tables and inserts missing sample records by ID. Repeating it
preserves existing records, including modifications. Normal server startup creates
missing tables but never seeds, clears or resets data; an unseeded database lists
`[]`. Stop the server before running initialization or reset.

To **discard all application data in the selected database** and restore samples:

```sh
python -m booking.database reset --yes
```

Reset requires `--yes`. Repeating reset produces the same sample state.

## Resources and worked example

```sh
curl http://127.0.0.1:8000/resources
```

In PowerShell use `curl.exe` or
`Invoke-RestMethod http://127.0.0.1:8000/resources`.
After fresh initialization, expect HTTP **200** and:

```json
[
  {"id": 1, "name": "Study room A", "kind": "room"},
  {"id": 2, "name": "Study room B", "kind": "room"},
  {"id": 3, "name": "Camera 01", "kind": "device"},
  {"id": 4, "name": "Camera 02", "kind": "device"}
]
```

`GET /resources` takes no parameters or identity header. It returns every stored
resource ordered by integer `id`; `name` is its display label, and `kind` describes
a room or device. Each camera is a separate physical device. Each resource is
reserved exclusively; capacity and inventory quantity do not determine
availability. This endpoint lists the catalogue, not available time slots.

## Simulated identity

Initialization persists users **1: Alex Chen** and **2: Sam Patel**. Booking
creation and cancellation use the `X-User-ID` header containing a seeded user's integer ID,
for example `X-User-ID: 1`. The acting user owns the booking; ownership is not
chosen through a request-body field. Resource and booking reads need no identity.
This is a local role simulation: anyone can choose either identity. There are no
passwords, login, authentication or user/resource administration endpoints.

## Booking API

| Operation | Request | Success |
| --- | --- | --- |
| `POST /bookings` | `X-User-ID` header and JSON below | 201, stored booking |
| `POST /booking-series` | `X-User-ID` header and JSON with `recurrence_count` | 201, stored weekly occurrences |
| `GET /bookings/{booking_id}` | Positive integer ID; no identity | 200, stored booking |
| `GET /bookings` | No parameters or identity | 200, all records in ID order, or `[]` |
| `GET /series/{booking_id}` | Positive occurrence booking ID; no identity | 200, complete series in chronological order |
| `POST /bookings/{booking_id}/cancel` | Positive integer ID and `X-User-ID`; no body needed | 200, retained cancelled booking |

IDs are positive integers up to 9223372036854775807. JSON resource IDs must be
integers. Single creation accepts only `resource_id`, `start` and `end`; extra
fields, including `owner_id`, `id`, `series_id` and `cancelled`, are rejected.

```json
{"resource_id": 1, "start": "2030-01-15T10:00:00", "end": "2030-01-15T11:00:00"}
```

Refresh the dates to be in the future before sending. A fresh database returns:

```json
{"id": 1, "owner_id": 1, "resource_id": 1, "start": "2030-01-15T10:00:00", "end": "2030-01-15T11:00:00", "cancelled": false}
```

The response above assumes `X-User-ID: 1`. Retrieval returns the same record.
Listing includes retained cancelled records; new bookings start uncancelled.
Bookings survive server restart and repeat `init`; `reset --yes` deletes them.

To create a weekly series, send the same fields plus an integer
`recurrence_count` from 1 through 12:

```json
{"resource_id": 1, "start": "2030-01-15T10:00:00", "end": "2030-01-15T11:00:00", "recurrence_count": 3}
```

The response is an array of occurrence bookings in chronological order. Each
occurrence is seven days after the previous one at the same campus-local time.
Every occurrence has a unique booking `id`, while `series_id` is shared and
equals the first occurrence's booking ID:

```json
[
  {"id": 1, "owner_id": 1, "resource_id": 1, "start": "2030-01-15T10:00:00", "end": "2030-01-15T11:00:00", "cancelled": false, "series_id": 1},
  {"id": 2, "owner_id": 1, "resource_id": 1, "start": "2030-01-22T10:00:00", "end": "2030-01-22T11:00:00", "cancelled": false, "series_id": 1},
  {"id": 3, "owner_id": 1, "resource_id": 1, "start": "2030-01-29T10:00:00", "end": "2030-01-29T11:00:00", "cancelled": false, "series_id": 1}
]
```

The series request does not accept `owner_id` or `series_id`; the acting user
owns every occurrence. Existing booking reads continue to use the single-booking
response shape and do not expose `series_id`.
### Retrieving a booking series

Use any occurrence's booking ID with `GET /series/{booking_id}` to retrieve the
complete series. No identity is needed. The response is a JSON array ordered by
the occurrences' start times, with booking ID as a deterministic tie-breaker.
Every item has the standard booking fields plus its shared integer `series_id`,
and cancelled occurrences remain in the result.

An unknown booking returns **404**. An existing standalone booking returns
**409** because it has no series. The existing booking endpoints do not expose
`series_id`; series membership is available only through this endpoint.

All timestamps represent **Toronto campus wall time** (`America/Toronto`), encoded
as `YYYY-MM-DDTHH:MM:SS` with optional 1–6 fractional second digits and **no offset
or Z**. Date-only values and numeric timestamps are rejected. The production
clock reads Toronto time independently of the machine's local timezone; the
pinned `tzdata` package supplies timezone data when the OS does not.
Timezone conversion and daylight-saving transition scenarios are outside this
simulation. Use ordinary dates away from those transitions.

Start must be strictly after now; end must be strictly after start. Duration
must be at most eight hours, including overnight bookings. Intervals include
start and exclude end, so 10:00–11:00 and 11:00–12:00 are adjacent and permitted.
Any overlap with an uncancelled booking on the same resource is rejected;
identical times on different resources are permitted.

Series creation applies the same time and conflict rules to every generated
occurrence. It checks the complete series before inserting any occurrence. If
one occurrence conflicts with an uncancelled single booking or recurring
occurrence, the request returns 409 and stores none of the proposed series. If
all occurrences are valid and available, they are stored in one transaction.
Existing `POST /bookings` conflict checks include recurring occurrences because
each occurrence is stored as a regular booking row.

Only the owner may cancel a booking. An active booking can be cancelled strictly
before its start; at or after start the request returns 409 and preserves it.
Cancellation returns the same record with `cancelled: true`, retains it in reads
and releases its slot for another valid booking. Owner retries return 200 with
the unchanged cancelled record, even after the original start. Ownership is
checked before retry handling, and cancelled state before the start-time rule.

```sh
curl -X POST -H 'X-User-ID: 1' http://127.0.0.1:8000/bookings/1/cancel
```

In PowerShell use `curl.exe`. Substitute the ID returned by creation.

These guarantees apply to **sequential requests**. A series is persisted
all-or-nothing within its request, but simultaneous requests can both observe
availability before either inserts a record. SQLite persistence alone does not
make the availability check and insertion an atomic reservation across requests.

Errors use `{"detail": "message"}` consistently:

| HTTP status | Meaning |
| --- | --- |
| 403 | `Only the owner can cancel this booking` |
| 404 | `Unknown user`, `Unknown resource` or `Unknown booking` |
| 409 | `Resource is already booked for this interval` or `Booking has already started` |
| 422 | `Invalid request shape or timestamp`, `Start must be in the future`, `End must be after start` or `Duration must be at most eight hours` |

A missing/malformed identity header also returns 422. Rejected single or series
creation and rejected cancellation leave all persisted bookings unchanged. Cancellation resolves the seeded user before
looking up the booking; unknown users and bookings return 404. The interactive docs describe these operations
and their response models.

### Run the full worked example

With the initialized server running, open a second terminal in this directory
and activate the same environment, then run:

```sh
python -m booking.example
curl http://127.0.0.1:8000/bookings
```

The example selects the first resource, books it tomorrow at 10:00–11:00 as user
1, retrieves the returned ID, cancels it and books the released interval as user
2. It prints the original, cancelled and replacement records. Listing shows both
the retained cancelled booking and its active replacement. Dates refresh each
run. Repeating it on the same day returns 409 because the interval is occupied;
use another interval in `/docs`, or stop the server, reset the sample database
and restart before repeating. In PowerShell use `curl.exe` for the second command.

## Verify and read the code

```sh
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy booking
```

For application line and branch coverage, use the CI test command:

```sh
python -m pytest --cov --cov-report=term-missing --cov-report=html
```

Open `htmlcov/index.html` to inspect executed and missing lines and branches.
The terminal's `Cover` column combines line and branch opportunities; the HTML
report also lets you inspect individual files. Coverage includes all `booking/`
modules, including modules not imported by the tests, and retains `.coverage`
with relative source paths for report processing. These generated files are ignored
by Git. A green check establishes that the supplied assertions passed; coverage
does not establish that assertions are sufficient or that every requirement holds.
There is no minimum percentage, no no-decrease gate and no coverage-based grading.

### GitHub Actions

When this directory is the root of its own repository, the included
[CI workflow](.github/workflows/ci.yml) runs the commands above on branch pushes
and pull requests using Python 3.14 on Ubuntu 24.04. New tests under `tests/`
are discovered automatically. Lint, formatting, type or test errors fail checks.
Coverage reports are uploaded even after test failures, without clearing the failure.
In the Actions run, download **application-coverage**, extract it and open
`htmlcov/index.html`. Reports are retained for 14 days, including in private
repositories; the artifact also contains `.coverage`.

After successful default-branch checks, a separate job stores comparison data on
`python-coverage-comment-action-data`. Pushes to that generated branch do not
trigger CI. PR runs prepare a comment with read-only permissions; the separate
[publishing workflow](.github/workflows/coverage.yml) posts or updates it after
successful CI, including approved fork runs. Publishing executes no PR code.
An unsuccessful later run leaves the previous comment in place; check its commit
and the current CI status before using it as evidence.

Repository setup: allow the pinned actions, enable Actions, and permit the
coverage-data branch to be created and updated by Actions. Both workflow files
must be on the default branch, with a successful reference run before comparing
PRs against it. Keep fork runs read-only; normal GitHub approval requirements for
fork contributors still apply. Private repositories should use the downloadable
HTML artifact rather than the action's public HTML preview links.
Only comparison-data storage receives `contents: write`; only comment publishing
receives `pull-requests: write`. No personal access token is needed.

Configuration follows the pinned
[Python Coverage Comment documentation](https://github.com/py-cov-action/python-coverage-comment-action/tree/5d8df5979747514c914e1c5a12335a7cf9a2745f),
[pytest-cov configuration](https://pytest-cov.readthedocs.io/en/latest/config.html)
and [Coverage.py relative paths](https://coverage.readthedocs.io/en/latest/config.html#run-relative-files).

### Code and test layout

Default pytest discovery is limited to `tests/`. Tests use temporary SQLite files
and do not touch your local database. Read `booking/models.py` for stored records,
`booking/database.py` for setup and sample data, and `booking/main.py` to trace the
requests through validation, SQLModel queries and JSON responses.
`booking/schemas.py` describes request and response shapes. API tests pass a
fixed offset-free Toronto datetime through `create_app(..., clock=...)`; there
is no HTTP endpoint for changing time. Exact dependencies,
including transitive packages, are pinned in `requirements.txt`.

Setup follows the official [Python 3.14 venv documentation](https://docs.python.org/3.14/library/venv.html).
The API and database test patterns follow the
[FastAPI first steps](https://fastapi.tiangolo.com/tutorial/first-steps/) and
[SQLModel testing guide](https://sqlmodel.tiangolo.com/tutorial/fastapi/tests/).
