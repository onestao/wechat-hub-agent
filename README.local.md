# Local WeChat Memory Suite

This workspace runs browser-based WeChat plus a read-only local memory pipeline.

## Services

- `wechat-selkies`: browser WeChat, exposed on `http://127.0.0.1:3000`.
- `wechat-memory-sync`: read-only decrypt/sync worker, writes `runtime/memory/wechat_memory.sqlite`.
- `wechat-ai-memory`: AI memory API and incremental indexer, exposed on `http://127.0.0.1:8090`.
- `wechat-agent-console`: unified console for chat viewer, service status, LLM/persona/memory layers, exposed on `http://127.0.0.1:8078`.

`wechat-memory-sync`, `wechat-ai-memory`, and `wechat-agent-console` use the same project image. Release deployments pull:

```bash
docker.io/xiaoguiwucan/linux-wechat-agent:latest
```

Local development can still build:

```bash
local/wechat-memory-suite:latest
```

## Data Boundaries

- Original WeChat data is mounted read-only into our memory services via `./config:/app/config:ro`.
- Generated decrypt copies and memory stores live under `runtime/`.
- AI memory data lives under `runtime/ai-memory/`.
- The AI memory service does not send messages, control WeChat, or write WeChat metadata.

## Deploy

```bash
docker compose up -d
```

Rebuild after code changes:

```bash
./scripts/dev-up.sh
```

## Useful Checks

```bash
docker compose ps
curl -sS http://127.0.0.1:8078/api/chats/summary | jq
curl -sS http://127.0.0.1:8090/api/status | jq
curl -sS http://127.0.0.1:8078/api/suite-status | jq
```

## AI Memory API

Search long-term memory:

```bash
curl -sS 'http://127.0.0.1:8090/api/search?q=微信&limit=5' | jq
```

Build context for a future bot:

```bash
curl -sS 'http://127.0.0.1:8090/api/context?chat=18725461928%40chatroom&q=微信&recent_limit=20&memory_limit=8' | jq
```

CLI helper:

```bash
python ai/cli.py status
python ai/cli.py chats
python ai/cli.py search 微信 --limit 5
```

## Decoupled Agent Service (Work Package E)

`agent_service/` is the new optional `wechat-agent` component. It is deliberately separate from Core and does **not** open Core SQLite databases. Its only WeChat boundary is Core HTTP V1:

```text
GET  /health
GET  /v1/accounts
GET  /v1/accounts/{account_id}/chats
GET  /v1/events/poll
POST /v1/events/ack
GET  /v1/media/{media_id}
POST /v1/send/text
```

It owns its own durable database containing event receipts/cursor state, event-derived AI memory, Records, Monitors, Templates, schedules and run history. Message identity is always account-aware.

The service reuses the original AI code instead of replacing it:

- event memory imports the original `memory/ai_memory_core.py` tokenization/vector/ranking primitives;
- group-summary actions call the original Console `read_config` / `active_profile` / `request_llm` path;
- image-understanding actions fetch the actual media bytes through Core, then call the original `request_vision_llm` / image profile path;
- builtin `agent_console/builtin_skills/*/SKILL.md` packages are exposed as the Agent skill catalog.

Run one contract/ingest cycle against Mock Core or Core:

```bash
WECHAT_CORE_URL=http://127.0.0.1:8080 \
python -m agent_service.app --once
```

Run the HTTP service:

```bash
WECHAT_CORE_URL=http://127.0.0.1:8080 \
WECHAT_AGENT_DB=runtime/agent-service/agent.sqlite \
python -m agent_service.app --host 127.0.0.1 --port 8091
```

Useful endpoints:

```text
GET  /health
GET  /api/skills
GET  /api/memory/search?q=...
GET  /api/memory/context?account_id=...&chat_id=...&q=...
GET/POST /api/records
GET/POST /api/monitors
GET/POST /api/templates
GET/POST /api/schedules
POST /api/poll
POST /api/scheduler/run
GET/POST /mcp
```

`POST /mcp` is the Streamable HTTP JSON-RPC endpoint; `GET /mcp` exposes an SSE capability stream. MCP tools include account/chat discovery, Core text sending, account-scoped memory search/context, Records, Monitors, Templates, Scheduler and an explicit event poll.

Run the Gate-5 tests:

```bash
python -m py_compile agent_service/*.py agent_service/tests/*.py
python -m unittest discover -s agent_service/tests -v
```

The tests use Mock Core and fake model adapters where appropriate. They prove contract behavior and source reuse wiring; they do not claim real WeChat login, external LLM availability, or real vision-model connectivity.
