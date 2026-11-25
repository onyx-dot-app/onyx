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
SQL statements, commits, connection checkouts, cache commands and threads started. No
product code knows about them.

## Run it

The services of a dev stack must be up.

```bash
cd backend
uv run python -m scripts.benchmark_chat_turn --json-out report.json
```

| Option | Use |
| --- | --- |
| `--scenarios` | `warm` (the second turn of a session), `new-session` (the send creates the session), `long-history` (a session with 40 turns) |
| `--turns` | Measured turns per scenario. The default is 30 |
| `--sample-ms` | Sample the stacks of all server threads at this interval. The report then holds `stack_samples`. It slows the run, so do not compare its timings |
| `--update-golden` | Store the digests and counts of this run as the expected values |

## Read the report

- **CPU per turn** is the CPU time of the API server process divided by the turns. It is the
  most stable timing on a busy machine.
- **Per turn** counts are almost exact. The server runs a few statements of its own between
  turns, so a count can be a fraction above a whole number.
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
| The answer is the mock answer; the saved answer equals the stream | Lost or changed content |
| One LLM request per turn | An added or lost model call |
| The reserved id comes before the answer | A break of `reserve-before-first-token` |
| Transcript digest equals golden | Any change to packet types, order, placement or content |
| LLM request digest equals golden | Any change to the prompt, history, tools or parameters |
| Statements, commits, cache commands and threads per turn not above golden | A change that adds round trips |
| No traceback in the API server log | An error that the stream hides |

The golden values are in `golden.json`. Dates and times in the LLM request are replaced
before the digest. A change that alters the prompt or the stream on purpose, or that lowers a
count, updates them with `--update-golden` in the same commit.
