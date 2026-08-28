# Evidence Table Sorting: Correctness–Latency Trade-off

- **Status:** Current design documented; optimization proposed
- **Date:** 2026-08-28
- **Scope:** Evidence Browser (`#/jobs`) Company and Salary sorting

## Name of the design tension

The broad design tension is **client-side responsiveness versus server-side global ordering correctness**. It can also be described as a **data-locality trade-off**: sorting data already resident in the browser is fast, while sorting the authoritative dataset on the server can produce globally correct results across pages.

The current backend technique is more specifically called **application-layer sorting before pagination**. RoleRadar loads matching database records into the Python process, sorts them in Python, and only then selects the requested page. This is different from **database sort pushdown**, where SQL performs `ORDER BY`, `LIMIT`, and `OFFSET`.

This document is an Architecture Decision Record (ADR) for that choice and its consequences.

## Context

The Evidence Browser displays up to 50 job listings returned by `GET /api/v1/jobs`. Users can sort by:

- **Company**, to group offerings with identical company names.
- **Salary**, using the midpoint of the disclosed salary range.

Sorting only the 50 rows currently displayed would be fast, but it would not necessarily produce the correct first 50 rows from the complete filtered dataset. For example, matching offerings from the same company could remain outside the loaded page.

The implementation therefore treats the server as authoritative for ordering.

## Current decision

RoleRadar currently uses server-side, application-layer sorting:

1. A column-header click changes the `jobSort` React state in [`frontend/src/main.jsx`](../frontend/src/main.jsx).
2. The sort field and direction become part of the payload key.
3. The old payload is cleared and the UI displays its loading state.
4. The browser requests `/api/v1/jobs?limit=50&sort_by=<field>&order=<direction>`.
5. `_filtered_source_listings` in [`roleradar/app/server.py`](../roleradar/app/server.py) queries matching `SourceListing` records and materializes them as Python objects.
6. Role-family and text-query filters may be applied in Python.
7. Python's `sorted()` orders the complete matching collection.
8. The backend slices the collection using `offset` and `limit`, serializes the selected 50 records, and sends the response.
9. React renders the newly ordered table.

The simplified data flow is:

```text
Column click
    -> clear current payload
    -> HTTP request
    -> SQLite query
    -> materialize all matches in Python RAM
    -> filter and sort in Python
    -> take 50 records
    -> serialize and return JSON
    -> render the new table
```

## Data residency

The complete dataset is not kept in browser memory.

| Location | Data held |
| --- | --- |
| SQLite | Persistent authoritative dataset |
| Python server | All matching listing objects, temporarily during each request |
| Browser | The returned page of at most 50 listings |

SQLite pages may also be held in the operating system's file cache, but that does not remove the Python materialization, sorting, HTTP, and rerendering work.

## Why this design was reasonable

The current choice provides several useful properties:

- Ordering is calculated across the complete filtered result set, not just visible rows.
- The browser has a bounded memory and transfer requirement.
- Sort semantics live in one backend implementation.
- The API can support future pagination without relying on each client to reproduce sorting rules.
- The implementation is straightforward for an initially modest local dataset.

## Latency consequences

Each click starts new work instead of rearranging data already held by React. Approximate interaction latency is therefore:

```text
request overhead
+ database scan and ORM materialization
+ Python filtering
+ Python sort, approximately O(N log N)
+ response metadata queries
+ serialization and transfer
+ React rerender
```

`N` is the number of records matching the current filters, even though only 50 records are returned. The work is repeated when the user toggles between ascending and descending order because sorted results are not cached.

The interface also clears the existing payload before the request finishes. Consequently, users see a full loading state. This does not necessarily make the backend slower, but it makes the delay more prominent and removes useful content while waiting.

Excel and many interactive web tables feel immediate because the sortable rows are already resident in the same process. They avoid the database query and network round-trip when a header is clicked.

## Additional semantic constraints

- Company grouping depends on identical normalized company names. Spelling or capitalization variants can form separate groups.
- Undisclosed salaries currently receive a sort value of zero.
- Salary sorting uses the raw disclosed range midpoint. Comparing records with different currencies or pay intervals can be misleading unless salaries are normalized first.

These concerns are separate from performance, but database sort pushdown must preserve or deliberately revise these semantics.

## Alternatives considered

| Approach | Interaction speed | Global ordering | Main trade-off |
| --- | --- | --- | --- |
| Sort the loaded 50 rows in React | Near-instant | No | Fast but can show an incorrect global page |
| Load every match into the browser once | Fast after initial load | Yes | Larger initial transfer, browser memory use, and stale-data handling |
| Keep the current Python sorting | Network-bound and grows with `N` | Yes | Simple but repeatedly materializes and sorts all matches |
| Push sorting and pagination into SQLite | Fast and scalable | Yes | Requires SQL joins, computed salary ordering, and SQL-compatible filters |
| Cache server responses by filter and sort | Fast on cache hits | Yes | Invalidation complexity; first request remains slow |
| Keep old rows visible while refetching | Improves perceived speed | Yes | Does not reduce backend execution time |

## Recommended direction

Retain authoritative server-side ordering, but replace application-layer sorting with **database sort pushdown**:

1. Express supported filters in SQL where practical.
2. Apply a stable SQL `ORDER BY` for Company and Salary.
3. Apply `LIMIT` and `OFFSET` before materializing ORM objects.
4. Run a separate `COUNT` query for the total result count.
5. Add deterministic tie-breakers, such as listing ID, so pagination remains stable.
6. Define how currency and salary interval normalization should affect Salary ordering.

Separately, use a **stale-while-revalidate** interaction in React:

- Keep the current table visible while the new order is requested.
- Mark the active header as busy.
- Replace the rows when the authoritative response arrives.
- Prevent stale responses from replacing a newer sort request.

This combination preserves global correctness, reduces backend work, and avoids a disruptive full-table loading state.

## Validation plan

Before and after optimization, record:

- Total matching records.
- API duration for Company ascending and descending.
- API duration for Salary ascending and descending.
- Browser click-to-table-update duration.
- Median (p50) and slow-case (p95) latency over repeated runs.
- Query plans for each SQL ordering strategy.

Correctness tests should include more records than the page limit so they prove that sorting occurs before pagination. They should also cover duplicate company names, undisclosed salaries, equal salary midpoints, and stable tie-breaking.

## Decision summary

The current design favors **global correctness and bounded browser state** over immediate local interaction. Its latency comes from performing a fresh request and repeatedly sorting the full matching dataset in Python before returning 50 rows. The intended evolution is to preserve server authority while moving ordering and pagination into SQLite and keeping the existing table visible during refresh.
