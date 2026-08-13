# Email Agent Workflow — Agentic Architecture

**Branch:** `feature/true-agentic-loop` — **AgentRuntime** with LLM-chosen tools.

Legacy predetermined flow (`AgentLoop`) is deprecated; see git history on `main` for the old diagram.

---

## Master Flowchart

```mermaid
flowchart TD
    subgraph RUN["RUN LEVEL — app/agent/runtime.py run()"]
        START([AgentRuntime.run])
        COUNT[get_email_count — deterministic]
        LIST[list_emails — deterministic]
        FOR_EACH{For each email_id}
        END([Return AgentRunResult])
    end

    subgraph PER_EMAIL["PER EMAIL — agentic loop _run_agentic_loop()"]
        SKIP_CHECK[ProcessingStateManager.should_skip]
        SKIP[Return skipped]
        CLAIM[claim_for_processing]
        INIT[Init AgentState]
        LLM[LLM decide_next_action → AgentDecision]
        HARNESS[AgentHarness validate decision]
        TOOL[AgentToolKit execute tool]
        UPDATE[Append tool result to state]
        FINAL{action == FINAL?}
        DONE[Persist outcome + log]
    end

    subgraph STORAGE["PERSISTENCE — data/agent.db"]
        DB[(SQLite agent.db)]
    end

    START --> COUNT --> LIST --> FOR_EACH
    FOR_EACH --> SKIP_CHECK
    SKIP_CHECK -->|Terminal| SKIP --> DB --> FOR_EACH
    SKIP_CHECK --> CLAIM
    CLAIM -->|Failed| SKIP
    CLAIM --> INIT --> LLM --> HARNESS
    HARNESS -->|Invalid| DONE
    HARNESS -->|CALL_TOOL| TOOL --> UPDATE --> LLM
    HARNESS -->|FINAL| FINAL
    FINAL --> DONE --> DB --> FOR_EACH
    FOR_EACH -->|Done| END
```

---

## Component Map

| Node | File | Role |
|------|------|------|
| Agent runtime | `app/agent/runtime.py` | Outer mailbox loop + inner agentic loop |
| Agent state | `app/agent/state.py` | `AgentState`, LLM-safe context |
| Decision schema | `app/agent/schemas.py` | `AgentDecision`, `AgentFinalOutput` |
| Harness | `app/harness/runtime.py` | Tool auth, limits, validation |
| Tool registry | `app/tools/registry.py` | Registered tool metadata |
| Tool execution | `app/tools/agent_toolkit.py` | Deterministic tool implementations |
| LLM providers | `app/llm/` | `decide_next_action()` structured output |
| Duplicate guard | `app/harness/state.py` | `ProcessingStateManager` |
| Reply validation | `app/harness/validator.py` | Pre-send checks |

---

## Agentic Loop Test

> Can the LLM decide what tool/action happens next based on current state and prior tool results?

**Yes** — each turn calls `llm.decide_next_action(state, tool_catalog)`; Python does not hardcode tool order after claim.

---

## Known Limitation (v1)

Mailbox-level operations (`list_emails`, `get_email_count`) are not LLM tools yet; only per-email tool selection is agentic.
