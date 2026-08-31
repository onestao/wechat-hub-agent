# SOURCE_AUDIT_E

Work package: E / Agent  
Branch: `feat/mcp-monitor-agent`  
Audit date: 2026-08-31  
Upstream: `xiaoguiwucan/linux-wechat-agent` @ `58b2c43ff18597c6d0c9ec47270eb40e4fb0b2bb`

## 1. Repositories actually read

- `upstream/linux-wechat-agent` / the derived `work/agent` checkout.
- Shared contract only: `stack/contracts/openapi.yaml`, `docs/INTERFACE_CONTRACT_V1.md`, `stack/mock-core/app.py`.

No Core implementation database is read by this package. The Agent boundary is Core HTTP V1 plus durable Core events.

## 2. Source files actually read

- `ai/app.py`
- `ai/cli.py`
- `memory/ai_memory_core.py`
- `memory/ai_memory_worker.py`
- `memory/message_parse.py` (through the AI memory call path)
- `agent_console/app.py`
- `agent_console/builtin_skills/image-understanding/SKILL.md`
- `agent_console/builtin_skills/web-search/SKILL.md`
- `Dockerfile`

Shared contract inputs read:

- `../../docs/SOURCE_MAP.md`
- `../../docs/INTERFACE_CONTRACT_V1.md`
- `../../stack/contracts/openapi.yaml`
- `../../stack/mock-core/app.py`

## 3. Directly reusable code / behavior

| Original source | Symbol / behavior | Reuse in E |
|---|---|---|
| `memory/ai_memory_core.py` | `terms_for_text`, `vector_for_text`, `pack_vector`, `unpack_vector`, `cosine`, deterministic FTS/vector ranking ideas | Reused by the Agent-owned event memory index. The source DB reader is deliberately not reused because E may not open Core SQLite. |
| `memory/ai_memory_core.py` | `search_chunks`, `build_context` behavior | Preserved as the compatibility semantics for search/context; new account-aware event-memory search uses the same scoring primitives and result shape concepts. |
| `memory/ai_memory_worker.py` | periodic worker, stop flag, status/write pattern | Reused as the lifecycle pattern for Core event polling and the scheduler loop. |
| `agent_console/app.py` | `read_config`, `active_profile`, `request_llm`, `request_vision_llm`, `build_agent_system_prompt` | Reused at runtime through a compatibility adapter; model transport and vision invocation are not reimplemented. |
| `agent_console/app.py` | existing semantic memory / group-summary prompts and persistence concepts | Group-summary Monitor action keeps the existing LLM profile and system/personality path instead of creating a new model configuration stack. |
| `agent_console/builtin_skills/*/SKILL.md` | packaged skill metadata and instructions | Reused as the Agent skill catalog exposed through HTTP/MCP. |
| `ai/app.py` | small stdlib HTTP service pattern | Reused structurally for the standalone Agent HTTP server and JSON responses. |

## 4. Code that must be modified or adapted

### Existing AI memory source coupling

`memory/ai_memory_core.py:index_once`, `source_rows`, `recent_messages`, `list_chats` open the old local `runtime/memory/wechat_memory.sqlite`. That is valid in the old monolith but violates the frozen C/D/E boundary if pointed at Core storage. E therefore keeps the AI/vector primitives and introduces an **Agent-owned event memory database** populated from `/v1/events/poll`.

### Existing model / vision path

`agent_console/app.py` already contains the working model profile resolution, OpenAI-compatible transport and vision payload logic. The new service calls those functions through an adapter. It does not fork another provider implementation.

The derived checkout also adds one narrow compatibility guard around the unrelated `status/app.py` import. That helper requires a Unix Docker socket and prevented the AI functions from even being imported in the Windows development host. On Linux it still loads normally; on a host without `AF_UNIX`, only suite-status becomes unavailable while the original AI functions remain reusable.

### Existing skills

The builtin skill packages currently live under Console ownership. E treats those packages as read-only reusable skill definitions and exposes their metadata from the standalone Agent. Execution remains capability-specific; image understanding reuses the existing vision path.

## 5. Functionality that must be newly added

The upstream project does not contain a decoupled, Core-HTTP-only implementation of the following, so E adds them:

- Core V1 HTTP client with contract-version guard and event ack.
- Agent-owned event-memory ingest with explicit `(account_id, message_id)` identity.
- Streamable HTTP MCP endpoint and MCP tools.
- Durable Records store.
- Durable Monitor definitions and event-triggered actions.
- Durable Templates.
- Durable Scheduler jobs and run history.
- Standalone Agent HTTP API / health/status.

## 6. Explicitly not reused

- Direct reads of `runtime/memory/wechat_memory.sqlite`: rejected because E must use Core HTTP only.
- Console reply/outbox sender and `wechat_controller.py`: rejected for E because sending is owned by Core `/v1/send/*`; direct GUI/window control would violate component ownership.
- Console Docker/socket control endpoints: rejected because Agent must remain optional and decoupled.
- The old single-chat usernames as global identity keys: rejected because the frozen contract requires account scope.
- Rebuilding web search/provider clients inside E: rejected; existing skill definitions/model path stay the source of truth and additional providers are outside Gate 5.

## 7. Test entrypoints

- `python -m unittest discover -s agent_service/tests -v`
- Mock-Core integration test starts `stack/mock-core/app.py` in-process and points the Agent Core client at it.
- `python -m agent_service.app --once` performs a single poll/scheduler cycle without requiring a long-running server.

Mock Core tests are contract tests only. They are not evidence of real WeChat, Telegram, image-model, or external LLM connectivity.

## 8. Risks

- Core V1 exposes chats and events but no historical message-list endpoint. Agent memory can therefore ingest retained/new events, not backfill arbitrary historical messages through V1. This is a contract limitation and must not be worked around by reading Core SQLite.
- Vision/group-summary actions require a configured model endpoint. Tests use a fake adapter and do not claim real model connectivity.
- MCP protocol clients differ in how aggressively they require SSE/session behavior. The implementation targets Streamable HTTP request/response semantics and keeps stateless JSON-RPC operation available; interoperability should be rechecked against the actual MCP client used in deployment.
- Event delivery is at least once, so every action must be idempotent by `event_id` / deterministic action key.

## 9. Real modification locations for work package E

- `agent_service/` — new decoupled Agent service, built around the audited reusable AI pieces.
- `agent_console/app.py` — narrow optional guard for the non-AI Unix-socket status helper so the original LLM/vision functions can be reused cross-platform.
- `Dockerfile` — package and run the Agent service while keeping the original AI/Memory/Console source available for reused functions.
- `README.local.md` — standalone Agent run/config instructions and explicit component boundary.
- `SESSION_E_COMPLETION.md` — Gate-5 evidence and source-utilization report.

