# Session E Completion Report

Work package: E / Agent  
Branch: `feat/mcp-monitor-agent`  
Date: 2026-08-31  
Taskbook gate: Gate 5 — audited AI/Memory + MCP/Monitor/Records

## Result

The decoupled `wechat-agent` implementation is complete for the frozen Core V1 development boundary.

Implemented and tested:

- Core V1 HTTP client with contract-version check.
- Durable at-least-once event consumer state (`event_id`, cursor and ack handling).
- Account-aware Agent-owned event memory.
- Reuse of upstream AI-memory tokenization/vector/ranking primitives.
- Reuse of upstream model profile, LLM request and vision request paths.
- Reuse/exposure of upstream builtin skill packages.
- Streamable HTTP MCP endpoint (`POST /mcp`, SSE `GET /mcp`).
- Monitor Engine with durable definitions/run history and idempotent actions.
- Records, safe Templates, and durable Scheduler.
- Standalone HTTP API and runnable container entrypoint.

The Agent never opens Core SQLite. Mock-Core integration is contract evidence only; it is not presented as a real WeChat or external-model test.

## Boundary / decoupling proof

All WeChat reads/writes in `agent_service/` go through `CoreClient`:

```text
GET  /health
GET  /v1/accounts
GET  /v1/accounts/{account_id}/chats
GET  /v1/events/poll
POST /v1/events/ack
GET  /v1/media/{media_id}
POST /v1/send/text
```

The Agent SQLite file contains only Agent-owned state:

```text
agent_meta
event_receipts
event_memory_chunks
event_memory_vectors
event_memory_fts
records
templates
monitors
monitor_runs
schedules
scheduler_runs
```

Every event-memory message key carries `account_id`; `event_memory_chunks` also has a unique `(account_id, message_id)` index. Monitor send actions call Core with deterministic idempotency keys rather than touching the GUI sender.

## Source reuse

### Event memory

`agent_service/memory_index.py` consumes normalized Core message events and deliberately does not use the old source-DB readers. It directly imports these primitives from `memory/ai_memory_core.py`:

```text
terms_for_text
vector_for_text
pack_vector
unpack_vector
cosine
sanitize_fts_query
keyword_score
DEFAULT_DIM
```

This preserves the original deterministic vector + FTS strategy while adding account scope and the Core HTTP boundary.

### Existing LLM and image understanding

`agent_service/legacy_ai.py` lazily loads `agent_console/app.py` and calls the existing:

```text
read_config
active_profile
request_llm
request_vision_llm
build_agent_system_prompt
image_skill_profile (when present)
```

No second model HTTP client is implemented in Agent. Image Monitor actions first fetch real bytes through Core `/v1/media/{media_id}`, then pass them to the reused vision path.

The derived `agent_console/app.py` has one narrow compatibility guard: the unrelated `status/app.py` Unix-socket helper is optional on hosts without `AF_UNIX`. Linux behavior remains normal; this lets the original AI functions be imported on the Windows development host.

### Builtin skills

The Agent scans the existing `agent_console/builtin_skills/*/SKILL.md` packages and exposes their metadata from `/api/skills`; the skill definitions are not recreated under `agent_service/`.

## New features

### Monitor Engine

Durable filters: `event_type`, `account_id`, `chat_id`, `message_type`, `contains_text`.

Actions:

```text
record
send_text
summary
image_understanding
```

Each action uses a deterministic `monitor_id:event_id:action` key. Core sends additionally use deterministic `Idempotency-Key` values.

### Records / Templates / Scheduler

Records are durable and account/chat scoped. Templates only expand `{{ dotted.path }}` fields and never evaluate expressions.

Scheduler task types are `record`, `send_text`, and `summary`. Schedule definitions and run history survive restarts in the Agent database; scheduled Core sends are idempotent per schedule/due-time.

### MCP Streamable HTTP

Supported JSON-RPC MCP methods:

```text
initialize
ping
tools/list
tools/call
notifications/initialized
```

Transport:

```text
POST /mcp  -> Streamable HTTP JSON-RPC request/response
GET  /mcp  -> text/event-stream capability event
```

Initial tools:

```text
wechat_accounts
wechat_chats
wechat_send_text
memory_search
memory_context
records_list
records_create
templates_list
templates_upsert
monitors_list
monitors_upsert
scheduler_list
scheduler_upsert
agent_poll
```

## Validation performed

### Python compile

Passed:

```text
python -m py_compile agent_service/__init__.py agent_service/core_client.py agent_service/storage.py agent_service/templates.py agent_service/memory_index.py agent_service/legacy_ai.py agent_service/monitor.py agent_service/scheduler.py agent_service/service.py agent_service/mcp.py agent_service/app.py
```

### Unit + Mock Core integration

Passed:

```text
python -m unittest discover -s agent_service/tests -v

Ran 8 tests in 3.610s
OK
```

Coverage includes account-scoped memory, duplicate indexing, safe Templates, Monitor idempotency, summary/image adapter calls, Scheduler persistence, real in-process `stack/mock-core/app.py` HTTP poll/ack, two-account ingest, MCP tool calls, Core text send, and actual HTTP `POST /mcp` plus SSE `GET /mcp`.

### Real upstream-derived AI function import

Passed on the Windows development host after isolating the non-AI Unix-socket status helper:

```text
request_llm True
request_vision_llm True
active_profile True
skills 4
```

This confirms the production adapter can load the actual reused functions; no rewritten production model client is substituted.

## Not tested / environment limitations

- Real WeChat login/message traffic belongs to Runtime/Core integration and was not available to E.
- No external LLM credential/connectivity claim is made.
- No real external/local vision-model response claim is made.
- Session 0 recorded that Docker is not installed on this host; the Dockerfile is wired but an image build cannot be claimed here.
- Frozen Core V1 has no arbitrary historical-message listing endpoint. E does not bypass that limitation by opening Core SQLite, so event memory starts from retained Core events available to its consumer.

## Upstream used

```text
https://github.com/xiaoguiwucan/linux-wechat-agent.git
58b2c43ff18597c6d0c9ec47270eb40e4fb0b2bb
```

Shared contract sources:

```text
docs/INTERFACE_CONTRACT_V1.md
stack/contracts/openapi.yaml
stack/mock-core/app.py
```

## Reused code

| Original file | Original function/behavior | New caller | Adaptation |
|---|---|---|---|
| `memory/ai_memory_core.py` | `terms_for_text`, `vector_for_text` | `agent_service/memory_index.py` | Direct imports applied to Core-event text. |
| `memory/ai_memory_core.py` | `pack_vector`, `unpack_vector`, `cosine` | `agent_service/memory_index.py` | Direct imports with Agent-owned account-scoped chunks. |
| `memory/ai_memory_core.py` | `sanitize_fts_query`, `keyword_score` | `agent_service/memory_index.py` | Direct imports preserving hybrid search. |
| `memory/ai_memory_worker.py` | periodic worker lifecycle pattern | `agent_service/service.py` | Adapted from local index polling to Core event/scheduler loops. |
| `agent_console/app.py` | `read_config`, `active_profile` | `agent_service/legacy_ai.py` | Direct runtime calls. |
| `agent_console/app.py` | `request_llm` | `agent_service/legacy_ai.py` | Direct summary call; model transport not duplicated. |
| `agent_console/app.py` | `request_vision_llm`, `image_skill_profile` | `agent_service/legacy_ai.py` | Direct calls after Core media fetch. |
| `agent_console/app.py` | `build_agent_system_prompt` | `agent_service/legacy_ai.py` | Preserves existing personality/safety config. |
| `agent_console/builtin_skills/*/SKILL.md` | skill metadata/instructions | `/api/skills` | Existing packages are scanned, not rewritten. |
| `ai/app.py` | stdlib threaded HTTP pattern | `agent_service/app.py` | Pattern retained with a Core-only Agent boundary. |

## New code

- `agent_service/core_client.py`: Core V1 boundary absent upstream.
- `agent_service/storage.py`: standalone durable Agent state absent upstream.
- `agent_service/memory_index.py`: Core-event-to-existing-AI-memory bridge absent upstream.
- `agent_service/monitor.py`: generic Monitor Engine absent upstream.
- `agent_service/scheduler.py`: generic durable scheduler absent upstream.
- `agent_service/templates.py`: safe generic template renderer absent upstream.
- `agent_service/mcp.py`: MCP Streamable HTTP tool layer absent upstream.
- `agent_service/app.py`: standalone Core-only Agent HTTP service absent upstream.
- `agent_service/tests/`: Gate-5 contract/regression coverage absent upstream.

## Not reused

- `memory/ai_memory_core.py:open_source_db`, `source_rows`, `recent_messages`, old `index_once`: not used because they read the monolith's local memory SQLite; pointing them at Core would violate the frozen boundary.
- `agent_console/wechat_controller.py` and GUI sender paths: not used; Agent sends through Core HTTP.
- Console `reply_outbox`: not used for delivery; Core owns outbound state/idempotency.
- Console suite/container controls: not used; Agent remains optional and decoupled.
- Windows/GUI-specific runtime behavior: outside E ownership.

## Files changed by Session E

```text
SOURCE_AUDIT_E.md
SESSION_E_COMPLETION.md
Dockerfile
README.local.md
agent_console/app.py
agent_service/__init__.py
agent_service/app.py
agent_service/core_client.py
agent_service/legacy_ai.py
agent_service/mcp.py
agent_service/memory_index.py
agent_service/monitor.py
agent_service/scheduler.py
agent_service/service.py
agent_service/storage.py
agent_service/templates.py
agent_service/tests/*
```

## Integration handoff

Default container settings:

```text
WECHAT_CORE_URL=http://wechat-core:8080
WECHAT_AGENT_DB=/data/wechat-agent.sqlite
WECHAT_AGENT_CONSUMER_ID=wechat-agent
port 8091
```

Mount persistent storage at `/data` for production. Agent remains optional: removing it does not change Runtime/Core behavior, and it has no Core database dependency.

