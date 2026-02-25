# Minimal Learning Stack: AI Moat via Data Flywheel

## Context

The logistics agent is feature-complete but stateless — every session is lost on exit.
The strategic opportunity: every user query is a **revealed preference** about how real operators
phrase logistics trade-offs and what solver outputs they find valuable. That signal, accumulated
over sessions, is a proprietary moat no competitor can buy or synthesize.

---

## Why This Is a Moat, Not a Feature

**The flywheel has three turns:**

1. **Capture** — every (query → params → outcome) tuple is a ground-truth mapping from
   domain language to solver inputs. These are impossible to fabricate.

2. **Improve** — logged tuples become few-shot examples injected into the system prompt.
   Claude's parameter inference improves because it learns *this population's* vocabulary.

3. **Attract** — better inference = fewer correction turns = faster answers = more use =
   more data. Each revolution compounds.

**What becomes proprietary over time:** the `interactions.jsonl` file. After 6 months it contains
the exact vocabulary real logistics operators use, which constraint combinations are popular,
and which solver objectives users actually trust. No shortcut to replicate it.

**Inflection point:** ~50–75 rated sessions. At that volume, few-shot filtering becomes
meaningful (coverage-focused examples for coverage queries). The system visibly outperforms
a generic Claude deployment.

---

## The Reinforcing Loop Design

```
User query
    ↓
Claude infers params (system prompt has few-shot examples from DB)
    ↓
Solver runs → result displayed
    ↓
[NEW] Interaction logged → JSONL (zero friction, always-on)
    ↓
At session exit: "How useful was this? [1/2/3]" → JSONL rating event
    ↓
At next startup: query SQLite for top-rated (query, params) pairs
    ↓
Inject as few-shot examples into system prompt
    ↓ (loop — each session starts smarter)
```

---

## Signal Map: What to Capture and Why

| Signal | Source in Code | Learning Value | Friction |
|---|---|---|---|
| `query_text` | `user_input` in main.py loop | Intent vocabulary | Zero |
| `inferred_params` | `agent.last_tool_results[0]["result"].params` | Language→params mapping | Zero |
| `solver_outcome` (feasible, cost, time, coverage) | `agent.last_tool_results[i]["result"].output` | What network produced | Zero |
| `solver_call_count` | `len(agent.last_tool_results)` | How much Claude explored | Zero |
| `agent_turn_count` | `agent.turn_count` property | Refinement depth | Zero |
| `session_rating` | Single exit-time prompt (1/2/3) | Labels all session queries | One keypress |

**What NOT to ask:** no per-query ratings — users ignore them. One session-level rating
anchors all queries in that session adequately.

---

## Feedback Surface

One prompt, one keypress, only at `quit`/`exit`/`q` or `KeyboardInterrupt`:

```
How useful was this session? [1=not useful / 2=ok / 3=very useful] (Enter to skip):
```

- Enter = skip, never blocks exit
- 1/2/3 appended as a `session_rating` event to JSONL
- No friction in the query-response loop at all

---

## Storage Architecture: JSONL + SQLite Dual Layer

**Location:** `~/.logistics_agent/` (persists across working directory changes)

### JSONL (primary write path)

Append-only, one JSON object per line. Atomic for small records. Human-readable.
Never fails silently — caught and swallowed, app continues.

**Interaction record:**
```json
{
  "schema_version": 1,
  "event_id": "uuid4",
  "session_id": "uuid4",
  "session_timestamp": "2026-02-23T14:32:01",
  "turn_index": 0,
  "query_text": "cheapest way to cover 80% of zones",
  "inferred_params": {"objective": "Total Cost", "min_service_coverage": 0.8},
  "solver_calls": [{"scenario_name": "...", "is_feasible": true, "total_cost": 939530, ...}],
  "solver_call_count": 1,
  "agent_turn_count": 3
}
```

**Rating event** (appended separately, linked by `session_id`):
```json
{
  "event_type": "session_rating",
  "session_id": "uuid4",
  "rating": 3,
  "total_queries": 4,
  "total_solver_calls": 6,
  "timestamp": "2026-02-23T14:45:12"
}
```

### SQLite (query layer)

Rebuilt from JSONL at process start (incremental sync — only new records added).
Enables pattern queries:

```sql
-- Few-shot retrieval
SELECT query_text, inferred_params_json
FROM interactions i
JOIN session_ratings sr ON i.session_id = sr.session_id
WHERE sr.rating >= 2
ORDER BY session_timestamp DESC LIMIT 5;

-- Objective popularity
SELECT inferred_params_json FROM interactions;  -- parsed in Python

-- Infeasibility patterns
SELECT inferred_params_json FROM interactions WHERE has_infeasible = 1;
```

**Tables:**

`interactions`:
- `event_id TEXT PRIMARY KEY`
- `session_id TEXT`
- `session_timestamp TEXT`
- `turn_index INTEGER`
- `query_text TEXT`
- `inferred_params_json TEXT`
- `solver_calls_json TEXT`
- `solver_call_count INTEGER`
- `agent_turn_count INTEGER`
- `has_infeasible INTEGER DEFAULT 0`

`session_ratings`:
- `session_id TEXT PRIMARY KEY`
- `rating INTEGER`
- `total_queries INTEGER`
- `total_solver_calls INTEGER`
- `timestamp TEXT`

---

## How Logged Data Improves Behavior

### Improvement 1 — Few-Shot Parameter Inference (active after ~20 sessions)

At startup, `logger.get_few_shot_examples()` fetches 5 most-recent rated (query, params) pairs.
These are injected at the end of the system prompt via `build_system_prompt()`:

```
EXAMPLES FROM RECENT SUCCESSFUL SESSIONS:
- "cheapest for 80% zones" → objective=Total Cost, min_service_coverage=0.8
- "fastest network no budget limit" → objective=Delivery Time
- "1 vehicle max per hub" → objective=Service Coverage, max_vehicles_per_warehouse=1
```

This directly improves Claude's disambiguation of ambiguous phrasings — the most common
failure mode in the current system.

### Improvement 2 — Constraint Pattern Hints (~50 sessions)

`get_popular_constraint_patterns()` returns objective frequency counts.
Popular constraint values (coverage thresholds users most request: 70%, 80%, 90%)
can be surfaced as a one-line hint in the prompt.

### Improvement 3 — Infeasibility Pre-Warning (~30 sessions)

`get_infeasibility_patterns()` returns params from interactions that produced infeasible results.
Constraint combinations that historically produce `is_feasible=False` can be noted in the prompt,
so Claude can warn the user before running the solver.

---

## File Structure

```
src/
  learning/
    __init__.py              — empty package marker
    logger.py                — InteractionLogger class (~180 lines)
    prompt_builder.py        — BASE_SYSTEM_PROMPT + build_system_prompt() (~60 lines)
  models.py                  — +InteractionRecord, +SessionRatingRecord (additive)
  claude_agent.py            — system_prompt param, turn_count property, _last_turn_count
  cli.py                     — +prompt_session_rating()
main.py                      — wiring: logger init, log_interaction, prompt_session_rating
learning-loop/
  loop-implementation.md     — this file
```

**Data directory:** `~/.logistics_agent/`
- `interactions.jsonl` — append-only primary store
- `interactions.db`    — SQLite query layer (rebuilt from JSONL on start)

---

## Resilience Design

Every public method on `InteractionLogger` catches and swallows all exceptions.
This means:

- Unwritable JSONL → `log_interaction()` silently returns, app continues
- Corrupted JSONL line → `_sync_jsonl_to_db()` skips it, no crash
- Deleted DB → rebuilt from JSONL on next startup
- DB locked → sync skipped, stale examples used (acceptable degradation)

The app **never fails due to logging**. The learning system is entirely additive to the
existing flow, not load-bearing.

---

## Verification Checklist

**Test 1 — Logger isolation (no API needed):**
```python
from src.learning.logger import InteractionLogger
logger = InteractionLogger()
# ~/.logistics_agent/ created, interactions.db exists

session_id = logger.new_session()
logger.log_interaction(session_id, 0, "test query", {"objective": "Total Cost"}, [], 2)
# ~/.logistics_agent/interactions.jsonl exists with valid JSON line

logger.log_session_rating(session_id, 3, 1, 0)
# second record appended

logger.get_few_shot_examples()  # returns [] (DB not yet synced)
logger._sync_jsonl_to_db()
logger.get_few_shot_examples()  # returns 1 record
```

**Test 2 — Prompt builder isolation:**
```python
from src.learning.prompt_builder import BASE_SYSTEM_PROMPT, build_system_prompt
assert build_system_prompt([]) == BASE_SYSTEM_PROMPT
result = build_system_prompt([{"query_text": "test", "params": {"objective": "Total Cost"}}])
assert "EXAMPLES FROM RECENT SUCCESSFUL SESSIONS" in result
```

**Test 3 — Full loop (manual):**
1. `python main.py`
2. Submit one query, verify result displays
3. Type `quit`, enter `3`
4. Verify `~/.logistics_agent/interactions.jsonl` has two records (interaction + rating)
5. Re-run `python main.py` — no errors on second start (DB sync works)
6. After 5 rated sessions (rating ≥ 2): verify few-shot block in prompt
   (add `print(dynamic_prompt[-300:])` before `ClaudeAgent(...)` temporarily)

**Test 4 — Resilience:**
- Delete `interactions.db` → verify it rebuilds from JSONL on next start
- Make JSONL unwritable → verify `log_interaction()` silently returns, app continues
- Corrupt one JSONL line → verify `_sync_jsonl_to_db()` skips it, no crash
