# Slide 1: Problem + Requirements

## The Business Problem

NovaAI receives customer emails daily — pricing questions, feature inquiries, demo requests, and more. Manual triage does not scale.

## What the Agent Must Do

- Poll a mailbox periodically
- Classify which emails need action
- Detect product/service inquiries
- Retrieve **only authorized** company information
- Generate grounded, professional replies
- Send replies and log everything

## Hard Requirements (Non-Negotiable)

1. **No duplicate processing** — persistent state, DB UNIQUE constraint, race-safe claims
2. **No LLM database access** — controlled tools only (`get_product_information`, `get_service_information`)
3. **Deterministic guardrails in code** — authorization, validation, state transitions are NOT prompt-based
4. **$0 offline demo** — MockEmailProvider + MockLLMProvider work without API keys; Mistral AI for production

---

# Slide 2: Architecture + Agent Loop

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│ EmailProvider│────▶│  AgentLoop   │────▶│  LLMProvider    │
│ (Mock/Gmail) │     │  (explicit)  │     │ (Mock/Mistral)  │
└─────────────┘     └──────┬───────┘     └─────────────────┘
                           │
                    ┌──────▼───────┐
                    │  Guardrails   │  ← deterministic
                    │  State Mgr    │  ← DB UNIQUE on email_id
                    │  Validator    │  ← restricted content check
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ CompanyData  │  ← ONLY authorized fields
                    │ Tools        │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ Repository   │  ← JSON files, NOT exposed to LLM
                    └──────────────┘
```

## Explicit Agent Loop (visible in `app/agent/loop.py`)

For each email: **skip check → claim → fetch → classify (LLM) → guardrails (code) → tool calls (code) → generate reply (LLM) → validate (code) → send → log state**

No hidden framework. Every step is readable in one file.

---

# Slide 3: Tools + Harness + Guardrails

## Guardrail #1: Duplicate Processing Prevention

- `processed_emails.email_id` is PRIMARY KEY
- State machine: `pending → processing → processed | failed | skipped`
- `claim_for_processing()` uses atomic insert + IntegrityError handling for race conditions
- Second run skips all previously processed emails

## Guardrail #2: Controlled Company Data Access

```
Mistral LLM → CompanyDataTools → CompanyDataService → AuthorizationService → Repository
```

- Mistral receives **zero** database credentials or query tools
- `execute_sql`, `query_database`, `list_all_products` are explicitly forbidden
- AuthorizationService strips restricted fields (`internal_cost`, `customer_list`, etc.) before data reaches the LLM

## Harness Components

| Component | Role | Type |
|-----------|------|------|
| ProcessingStateManager | Duplicate prevention | Deterministic |
| AgentGuardrails | Category filtering, step limits | Deterministic |
| ResponseValidator | Restricted content, empty check | Deterministic |
| CompanyDataTools | Authorized data retrieval | Deterministic |

---

# Slide 4: Deterministic vs Probabilistic + Testing Strategy

## Decision Split (Critical Design Choice)

| Deterministic (Code) | Probabilistic (Mistral AI) |
|---------------------|-----------------------------|
| Already processed? | Email intent classification |
| State transitions | Product/service inquiry detection |
| Authorization filtering | Reply generation |
| Tool permission checks | Context understanding |
| Response validation | |
| Send email / logging | |
| Retry limits | |
| Mistral API error handling | |

**Why:** Authorization and duplicate prevention must never depend on LLM judgment.

## Testing Strategy

**Unit tests (pytest)** — 28+ tests covering all deterministic logic:
- State management, duplicate protection, authorization, validation, full agent loop
- Mistral provider tested with **mocked client** — no real API key required

**Evals (separate framework)** — 20-email dataset measuring:
- Classification accuracy, inquiry detection, category accuracy, reply groundedness
- Uses Mistral AI when `MISTRAL_API_KEY` is set; MockLLM offline

---

# Slide 5: Demo Results + Limitations + Future Improvements

## Demo Results (Mock Provider)

```
Emails found:     10
Emails processed:  4-5 (product/service inquiries with replies sent)
Emails skipped:    4-5 (spam, job apps, partnerships, restricted requests)
Emails failed:     0
```

Second run: all 10 skipped (duplicate protection verified).

## Known Limitations

- MockLLM (default) uses keyword matching — set `LLM_PROVIDER=mistral` for production
- Mistral API requires network access and valid `MISTRAL_API_KEY`
- Gmail provider implemented but requires OAuth setup (not tested without credentials)
- Single-threaded processing — no concurrent email handling
- SQLite — not suitable for high-volume production
- Reply validation uses pattern matching — could add LLM-as-judge optionally

## Future Improvements

1. Async processing with job queue for scale
2. Human-in-the-loop approval for high-stakes replies
3. PostgreSQL + connection pooling for production
4. LLM-as-judge eval pipeline with structured scoring
5. Rate limiting and backoff for email provider API
6. Web dashboard (FastAPI endpoints) for monitoring agent runs

## Key Files for Code Walkthrough

1. `app/agent/loop.py` — the agent loop
2. `app/llm/mistral_provider.py` — Mistral AI integration with structured outputs
3. `app/harness/guardrails.py` + `app/harness/state.py` — guardrails
3. `app/tools/company_data_tools.py` — controlled tool access
4. `app/company/authorization.py` — authorization enforcement
5. `tests/unit/` — deterministic test coverage
