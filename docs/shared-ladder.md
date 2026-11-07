# Shared raw-stat ladder and private result ingestion

Accounts remain in the existing `accounts.sqlite3`. `ladder.py` adds separate
`ladder_events` and `ladder_results` tables referencing `accounts(name_key)`.
Existing scrypt credentials, account schema version and login behavior are
unchanged. The normal SQLite backup includes these tables. A separate component
version guards the result schema.

## Versioned result contract

The exact `tubisoft-match-result-v1` object has these fields:

| Field | Contract |
| --- | --- |
| schema | `tubisoft-match-result-v1` |
| product / mode | Title identity and mode slug; separate board scopes |
| worker / match / round | Bounded worker ID, unique process-run match ID and positive round number; together the retry identity |
| winner | 2 (Alpha), 3 (Bravo) or null (draw) |
| ranked | Explicit Boolean; ranked requires verified account participants on both sides |
| players | 1–16 rows containing only slot (0–15), account (shared canonical name or null), team (2/3) and stats |
| stats | Exact nonnegative signed-32-bit counters: kills, deaths, team_kills, suicides, shots, hits, play_ms, rounds_won |

Unknown fields, duplicate accounts/slots, missing statistics, booleans used as
integers and unknown account references are rejected. A transaction inserts the
whole round or nothing. Canonical account case/order makes equivalent retries
identical. Identical retries return their original credit decision; changed
content under the same event ID returns a conflict. Concurrent retries credit
one round. Unranked reports are retained but never contribute to boards.

**Worker authentication and player account authentication are distinct.** The
private ingestion endpoint trusts an authorized worker to report verified
principals. It does not authenticate a client-supplied player name. GR2's current
open gameplay worker admits guests; its live reports are therefore unranked.
A verified GS-to-gameplay identity handoff remains necessary for live account
credit. Guest play is unaffected and no tester allowlist is introduced.

## Optional ingestion service

Disabled by default. Configure these variables together in the Python service:

```sh
TUBISOFT_RESULTS_PORT=8081
TUBISOFT_RESULTS_KEYRING=/state/private-worker-grants.json
```

The keyring is a private JSON list. Each entry has `worker`, `key_file` and
`products`, for example a worker ID and `["GHOSTRECON2PS2"]`. `key_file` points to
a separate private file containing a unique printable random key of at least
32 bytes, up to 256 bytes. Relative paths resolve against the keyring directory.
Do not commit either file; use mode 0600. The worker identity/product scope must
match the incoming report.

Only a loopback listener is allowed. Use a private authenticated tunnel or a
supervisor process in the same network namespace. With the current Docker
layout, loopback is **inside the service container**; a host port mapping alone
does not reach a container-loopback socket. The existing Compose template does
not enable or publish this endpoint. Provision a same-namespace sender/tunnel
before enabling ingestion; never expose it as a public account endpoint.

The HTTP route is `POST /v1/results` with `Authorization: Bearer <private-key>`.
The handler bounds headers, body, active requests and timeouts. SQLite work runs
off the event loop. It logs no report body or credentials. Responses:

| Status | Meaning |
| --- | --- |
| 201 / 200 | New / identical existing result; Boolean `inserted` and `credited` receipt |
| 400 / 401 / 403 | Invalid schema / worker authentication / worker or product scope |
| 409 / 422 | Conflicting retry / unknown shared account; entire report rejected |
| 503 | Capacity or database unavailable; retry later |

Worker keys are trusted report-writing authority, scoped per product. They do
not establish the original Ubisoft skill formula or prove retail gameplay.
There is no automated report retention or blocked-report correction UI yet.

## Board policy and native GR2 adapter

Raw boards are product-scoped, optionally mode-scoped. Ordering is **Tubisoft
policy**: team wins descending, kills descending, deaths ascending, canonical
account as tie-breaker. This is not Ubisoft Elo/skill/rating. Hits may exceed shots
because one shot can produce several source hit events; ratios are not invented.
The service stores no country/geolocation data.

Inspect privately with:

```sh
tubisoft-admin ladder --database /path/to/private/accounts.sqlite3 \
  --product GHOSTRECON2PS2 --mode assault
```

An experimental native query adapter is separately opt-in:
`TUBISOFT_NATIVE_RANKINGS=1`. Default behavior remains the verified empty-success
response. The adapter implements only selector 4 (named aliases), ladders 0
(overall), 1 Assault, 2 Sabotage, 3 Onslaught, 4 Team Survival. Unsupported
selectors/sort/filter/columns keep the empty path. A non-empty response returns
the recovered nine-column table: GLOBAL_RANK, ALIAS, COUNTRY, COUNTRY_ID, GRADE,
SCORE, KILL, TEAMKILL, DEATH. Both transport and application query IDs are kept.

For this new policy, SCORE is team wins, GRADE is zero, COUNTRY is empty and
COUNTRY_ID is zero. Table encoding and integer/string cell handling are tested;
**a populated table has not been accepted by a retail client yet**. Original
column-type descriptor spelling, other row-selection semantics, skill/grade
formulas and grade-dependent menu behavior still need retail/reference proof.
Do not enable it in production merely because the ledger tests pass.

The GR2 repository's `tools/gr2_results_lab.py` exercises the real loopback ingest,
duplicate/guest behavior, mode isolation and native codec roundtrip with
synthetic accounts. SQL tests also cover concurrent retries, atomic rollback,
account reuse and backup restoration. No original game assets are needed.
