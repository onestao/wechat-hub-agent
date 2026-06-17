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
