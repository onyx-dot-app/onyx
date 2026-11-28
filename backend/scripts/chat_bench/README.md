# Chat turn benchmark

Measures one chat turn: the time to the first answer token, and the work that the API server
does for it. It also checks that the stream, the LLM request and the saved turn are correct,
so a faster build that changes one of them fails.

Use it to compare two builds on one machine.

## What runs

| Part | Real or mock |
| --- | --- |
| API server, chat loop, agent runtime, LiteLLM, persistence | Real, one process started by the run |
| Postgres, Redis | Real. Own database (`chat_bench_db`) and Redis database (10) |
| LLM | Mock (`tests/integration/mock_services/mock_llm_server`), a fixed answer with no delay |
| OpenSearch, model server, file store | Not contacted. The server only makes the index `chat_bench_index` |

Setup drops and creates the database on each run, and refuses a database or index name
without the `chat_bench` prefix.

`scripts/chat_bench/server.py` starts the real API server with counters added from outside:
SQL statements, commits, connection checkouts, cache round trips and threads started. No
product code knows about them.

## Run it

The services of a dev stack must be up.

```bash
cd backend
uv run python -m scripts.benchmark_chat_turn --json-out report.json
```

| Option | Use |
| --- | --- |
| `--scenarios` | `warm` (the second turn of a session), `new-session` (the send creates the session), `long-history` (a session with 40 turns, which grows by one turn for each measured turn), `long-answer` (a warm turn whose answer comes in 300 chunks), `slow-llm` (a warm turn where the mock waits 0.5 s before its first chunk) |
| `--turns` | Measured turns per scenario. The default is 30 |
| `--sample-ms` | Sample the stacks of all server threads at this interval, and record the Onyx call site of each SQL statement. The stacks show where threads wait, not where the CPU goes. It slows the run, so do not compare its timings |
| `--update-golden` | Store the digests and counts of this run as the expected values |

## Read the report

- **CPU per turn** is the CPU time of the API server process divided by the turns. It is the
  most stable timing on a busy machine.
- **Per turn** counts are almost exact. The server runs a few statements of its own between
  turns, so a count can be a fraction above a whole number. A connection checkout also sends
  a pool ping, which the statement count does not include. A cache round trip is one command,
  one pipeline, or one WATCH or read inside a pipeline, on the sync or the asyncio client.
- **DB connections** shows how long the server keeps a connection checked out of the pool:
  the holds per turn, the total time held per turn, the longest hold, and the most connections
  held at one time. `db_connection_holds.longest` in the JSON report names the code that
  opened each of the 5 longest.
- **`slow-llm`** makes a connection that is held across the LLM call visible: such a hold
  lasts at least 0.5 s.
- **`long-answer`** shows the CPU for each streamed chunk. Compare its CPU per turn with
  `warm`: the difference is the cost of 300 chunks.
- The benchmark database has no license, no connector, no web search provider and no
  integration. Each request therefore takes the unlicensed path of the license check, and the
  tool checks take their path for an empty deployment.
- **First token** is split in three. *Before the LLM* ends when the mock receives the request:
  auth, turn preparation, tools, the run store and LiteLLM. *In the mock LLM* is a control
  value. *After the LLM* ends when the client reads the first content: accumulator, dispatcher,
  renderer, delivery and HTTP.
- **Body closed** minus **Stop** is the save and the release of the session.
- `breakdown_per_turn` in the JSON report lists each SQL statement shape and cache command
  with its count per turn.
- **Timings are not valid** when the host swaps. The run refuses to start above
  `--max-swap-pct` unless `--allow-swap` is set; the gates and the counts stay valid.

## Gates

The exit status is 1 when a gate fails.

| Gate | Catches |
| --- | --- |
| No error line, one `stop` per turn | A turn that failed or ended twice |
| The answer is the mock answer; the response that each turn reserved is saved with the streamed answer | Lost or changed content, or a save that did not happen |
| One LLM request per turn | An added or lost model call |
| The reserved id comes before the answer | A break of `reserve-before-first-token` |
| Transcript digest equals golden | Any change to packet types, order, placement or content |
| LLM request digest equals golden | Any change to the prompt, history, tools or parameters |
| Statements, commits, checkouts, cache round trips and threads per turn not above golden | A change that adds round trips, a commit or a thread |
| No database connection is held across the LLM call (`slow-llm`) | A session that stays open while the model works |
| No database connection is left open after the turns | A connection that a turn does not give back |
| Connections held at one time not above golden | A change that opens a second session while one is open |
| No traceback in the API server log | An error that the stream hides |

The golden values are in `golden.json`. Dates and times in the LLM request are replaced
before the digest. A change that alters the prompt or the stream on purpose, or that lowers a
count, updates them with `--update-golden` in the same commit.
