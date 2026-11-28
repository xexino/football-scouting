# Raja Scout MCP architecture

## Purpose and boundaries

The Model Context Protocol (MCP) lets AI agents call Raja Scout through a small set of typed
**tools**, acting as a signed-in user of one club.

- **The REST API stays the production integration interface.** MCP is an extra adapter for AI
  agents, built on the same code.
- **Status: development only.** No deployment file (`render.yaml`, `Dockerfile`,
  `docker-compose.yml`) starts the MCP server, and write tools are off. Exposing MCP to customers
  needs founder approval (see "Before production" below).

```
 AI agent (Claude Code, …)
   │  MCP: stdio (local dev)  or  Streamable HTTP + "Authorization: Bearer <token>"
   ▼
 app/mcp/server.py     tool schemas (types, ranges, enums) · write tools: preview → human approval
   │
 app/mcp/gateway.py    EVERY call: authenticate → membership + tenant context → RBAC
   │                   → rate limit → run → audit → safe errors
   ▼
 app/mcp/tools.py      thin adapters calling the existing endpoint functions/services
   │
 app/routers/*, app/analytics, app/serializers      (unchanged business logic & redaction)
   │
 SQLAlchemy session with tenant context → ORM tenant filter (app/tenancy.py) → PostgreSQL

 app/providers/        external data-provider boundary — separate; not imported by app/mcp
```

## How each security requirement is met

| Requirement | Implementation | Test (`backend/tests/test_mcp.py`) |
|---|---|---|
| Authenticate every connection | **HTTP:** the SDK bearer middleware calls our verifier (signature, expiry, active user, token version, membership) and rejects bad requests with **401 before any MCP processing**. **All transports:** `gateway.invoke` re-validates the token on *every tool call*, so revocation (`token_version` bump on password change or logout-all) takes effect immediately. | `test_anonymous_calls_are_refused_and_reveal_nothing`, `test_invalid_expired_and_revoked_tokens_are_refused`, `test_http_transport_authenticates_every_connection` |
| Organisation membership + tenant isolation | `security.get_ctx` (the same function the REST API uses) checks the active membership for the token's `org` claim and sets the session's tenant context. The ORM-level filter then hides other organizations' rows; `before_flush` blocks cross-tenant writes. Another club's record answers `not_found`. | `test_cross_tenant_private_records_are_invisible`, `test_rival_sees_its_own_records`, `test_write_against_other_tenant_is_refused` |
| Existing RBAC | Each tool declares permissions. A test proves they cover everything the wrapped endpoints require (`router_permissions` reads each endpoint's `Depends(require(...))`). Field-level redaction (financials) comes from the shared serializers. | `test_tool_permissions_cover_the_endpoints_they_call`, `test_role_without_permission_is_denied_and_audited`, `test_private_assessment_is_opt_in_and_financials_follow_rbac` |
| Never expose another club's private scouting records | Tenant filter (above); private assessments are per organization and opt-in per call | as above |
| No unrestricted SQL | No query/SQL tool exists; tenant sessions refuse Core SQL; all inputs map to fixed endpoint parameters | `test_no_raw_query_or_sql_tool_exists`, `test_input_validation` |
| Validate all inputs | JSON-schema types, ranges, lengths, enums and patterns, enforced by the SDK before the handler runs; endpoints validate again; undeclared arguments are dropped | `test_input_validation` |
| Rate limits | Per user, counted from the audit log over a 60-second window (`MCP_RATE_LIMIT_PER_MINUTE`, default 60). Works across workers and restarts without a new table. | `test_rate_limit_per_user` |
| Audit tool calls | `mcp.tool_call`, `mcp.tool_denied`, `mcp.rate_limited`, `mcp.write_preview`, `mcp.write_executed`, `mcp.write_declined` rows in the organization's audit log: tool, sanitised arguments (truncated), outcome, transport, duration. Tokens are never logged. Visible in Administration → Audit log. | `test_every_call_is_audited_without_secrets` |
| Keep provider API keys server-side | The MCP server holds no provider keys and makes no outbound calls. `app/providers` reads keys from server environment variables and redacts them from errors. | `test_mcp_server_is_separate_from_provider_adapters`, `test_provider_failures_degrade_safely` |
| Don't expose private assessments to providers | `app/providers` refuses requests containing private fields. MCP output labels them `organisation_private`, and the server instructions tell agents never to forward them. | `test_provider_policy_blocks_unverified_sources_and_private_data` |
| Explicit approval for consequential writes | Write tools are off by default and not even listed. When enabled: preview → **MCP elicitation** (human confirmation in the client) → re-authorised execution. A client that can't elicit is refused; the model can't self-approve (approval is not an argument); `request_state` round-trips are sealed with AES-GCM (key derived from `SECRET_KEY`, 5-minute TTL). | `test_write_tools_are_not_exposed_by_default`, `test_write_needs_human_approval_via_elicitation`, `test_write_still_enforces_business_rules_and_rbac` |
| API provider failures | `ProviderClient` maps timeouts, 401/403, 429, 5xx and malformed JSON to a typed `ProviderError` without secrets; unverified providers can't be instantiated for production | `test_provider_failures_degrade_safely` |
| No internal leakage | Unexpected exceptions return `internal_error` with a generic message; details go to the server log only | `test_internal_errors_do_not_leak` |

## Reuse, not duplication

- Tools call the endpoint functions directly through `gateway.call_endpoint`. It resolves FastAPI
  `Query(...)` defaults into real values and passes the gateway's context where the endpoint
  expects its auth dependency.
- So search filters, the comparison rules, pipeline transition rules (e.g. only roles with
  `pipeline:approve` may approve), report generation, subscription read-only mode and
  per-role redaction all behave exactly as in the web app.
- There are no new models and no migration. `get_club_requirements` is derived from existing
  pipeline and budget data.

## Transports

| Mode | Command | Authentication | Use |
|---|---|---|---|
| stdio | `backend/tools/raja-scout-mcp.sh` (= `python -m app.mcp`) | `RAJA_SCOUT_MCP_TOKEN` env var, checked on every call | Local development agents via `/.mcp.json` |
| Streamable HTTP | `python -m app.mcp --http --port 8001` (binds 127.0.0.1) | `Authorization: Bearer <token>` on every request; 401 otherwise | Remote agents later, behind TLS — **not deployed** |
| in-process | `build_server(token_source, ...)` | supplied token source | Tests |

Tokens are the platform's normal access tokens (`POST /api/auth/token`). They expire after
`TOKEN_EXPIRE_MINUTES` (8 h by default) and are bound to one organization. The stdio process must
use the same `SECRET_KEY` and `DATABASE_URL` as the backend.

## Development setup (Claude Code)

1. Run the backend with a fixed `SECRET_KEY` in your `.env`. Without one, a random key is
   generated at each start and tokens won't match.
2. Get a token:
   ```bash
   export RAJA_SCOUT_MCP_TOKEN=$(curl -s -d "username=you@club.com&password=..." \
     http://localhost:8000/api/auth/token | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
   ```
   Use a scout-level account for day-to-day agent work (least privilege).
3. Start Claude Code in the repository and approve the project MCP servers `raja-scout` and
   `football-docs`. For `sportmonks-football`, export your own `SPORTMONKS_API_TOKEN` first.
4. Secrets are expanded from your shell environment (`${VAR}` in `.mcp.json`). Nothing secret is
   committed.

Verified end to end on 2026-11-28: backend started → login → launcher over stdio →
`find_young_talents` and `get_club_requirements` returned the demo club's data → both calls
appeared in the app's audit log with `transport: stdio`.

## External provider adapters (`app/providers`)

- Kept separate on purpose: the MCP server never imports it. If agents ever need provider data,
  it will reach them through our own reviewed, licence-checked adapters, never by giving the
  agent a provider key.
- Policy in code:
  - a production client can only be built for a provider marked `VERIFIED-COMMERCIAL-OK`;
  - https only, and keys from the environment only;
  - private fields are refused, and errors are sanitised.
- No concrete adapter is enabled today: no paid provider is approved, and no subscription has been
  bought.

## Test results (2026-11-28)

- `backend/tests/test_mcp.py`: **22 passed**.
- Full suite on **SQLite: 155 passed, 3 skipped**.
- Full suite on **PostgreSQL 16: 155 passed, 3 skipped**.

## Before production (founder decisions)

1. **Approve exposing MCP to customers at all.** That includes which plan includes it; the
   suggestion is Club Pro / Enterprise.
2. **Deploy the HTTP transport** behind TLS, on its own hostname. Set `PUBLIC_BASE_URL`, and keep
   `TRUSTED_PROXY_HOPS` correct.
3. **Dedicated agent tokens.** Consider scoped, revocable tokens (an `aud: mcp` claim, shorter
   expiry, per-token revocation) instead of reusing login tokens. Today a leaked agent token is as
   powerful as that user's session.
4. **Enable write tools** (`MCP_WRITE_TOOLS_ENABLED=true`) only after reviewing the approval UX in
   the MCP clients the clubs actually use.
5. **Rate limits:** the audit-log counter is fine at small scale. Move to Redis or a dedicated
   table if call volume grows.
