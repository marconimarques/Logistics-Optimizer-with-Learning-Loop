# Logistics Optimizer with Learning Loop

> **Prototype:** This is a hands-on exercise in building one of the core moats available to AI-native applications: **Compounding Loops** — feedback mechanisms that make the product smarter and more defensible with every use. 

An interactive CLI that combines **Claude** as an AI agent with a **Pyomo + HiGHS MILP solver** to optimize logistics networks in plain English. Describe what you want — minimize cost, push coverage, enforce delivery constraints — and Claude decides which solver calls to make, interprets the results, and presents a structured analysis. All in a single terminal process, with no server to start.

What makes it distinctive: the app **learns from your sessions**. Each rated interaction is stored locally and used to improve Claude's parameter inference in the next session — a small but concrete example of how usage data compounds into a capability advantage that a generic deployment cannot replicate.

---

## What It Optimizes

The network consists of **5 warehouses** and **20 delivery zones**. For any given goal, the solver decides:

- Which warehouses to open
- Which zones each open warehouse serves
- How many vehicles to allocate per warehouse

### Objectives

| Objective | What the solver does |
|-----------|----------------------|
| `Total Cost` | Minimizes fixed warehouse costs + vehicle costs + delivery costs |
| `Delivery Time` | Minimizes the weighted sum of delivery times across all zone assignments |
| `Fleet Utilization` | Minimizes total vehicles across the network |
| `Service Coverage` | Maximizes the number of zones served |

### Constraints (combinable with any objective)

| Parameter | Effect |
|-----------|--------|
| `max_delivery_time` | Bans any warehouse–zone pair exceeding the time limit |
| `max_vehicles_per_warehouse` | Caps fleet size at each individual warehouse |
| `min_service_coverage` | Forces the solver to serve at least N% of all zones |

---

## Quick Start

### Prerequisites

- Python 3.10+
- An Anthropic API key

```bat
set ANTHROPIC_API_KEY=your_key_here
```

### Install

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### Run

```bash
python main.py
```

---

## Example Session

```
You: Minimize cost while covering at least 80% of zones
Answer: Serving 80% of zones (16 out of 20) only requires Industrial-1 as the
sole warehouse, with 7 vehicles at a total cost of $935,810.

You: Compare that against the fastest possible network
Answer: The fastest network opens all 5 warehouses with 10 vehicles each,
cutting average delivery time to 1.58 hours — but at a cost of $5,983,640,
roughly 6x more expensive.

You: What if I cap vehicles at 3 per warehouse?
Answer: With a 3-vehicle cap, the optimizer opens 3 warehouses covering 18
zones at $2,341,200 and an average delivery time of 1.84 hours.
```

### Built-in commands

| Command | Action |
|---------|--------|
| `help` | Show available commands and example queries |
| `clear` | Reset conversation history |
| `quit` | Exit and optionally rate the session |

---

## How It Works

### Architecture

```
User types a query
       │
       ▼
  main.py  ─── interaction loop, exception handling, learning wiring
       │
       ▼
src/claude_agent.py  ─── sends message to Claude (claude-sonnet-4-6)
       │                 maintains multi-turn conversation history
       │                 runs agentic loop (up to 10 iterations)
       │
       ├──[tool_use]──▶  src/solver.py  (Pyomo + HiGHS MILP, in-process)
       │◀──────────────  returns SolverResult
       │
       └──[end_turn]──▶  returns Claude's text analysis
       │
       ▼
  main.py  ─── renders solver tables via src/cli.py
               prints Claude's analysis
               on exit: prompts for session rating [1 / 2 / 3]

       ↑ Next startup: few-shot examples from rated sessions
         injected into the system prompt
```

### Separation of concerns

Each file has exactly one job:

| Layer | File | Responsibility |
|-------|------|----------------|
| Orchestration | `main.py` | Loop control, routing, exception handling, learning wiring |
| AI agent | `src/claude_agent.py` | Anthropic API, tool-use loop, conversation history |
| Solver | `src/solver.py` | MILP model, HiGHS, result extraction |
| Display | `src/cli.py` | Rich terminal output — zero business logic |
| Data contracts | `src/models.py` | Pydantic types shared across all layers |
| Learning — storage | `src/learning/logger.py` | JSONL write, SQLite sync, example retrieval |
| Learning — prompt | `src/learning/prompt_builder.py` | System prompt + few-shot injection |

`cli.py` never calls the solver. `solver.py` never prints anything. `claude_agent.py` never formats output.

### Network data

| Warehouse | Fixed cost | Capacity | Base delivery time |
|-----------|------------|----------|--------------------|
| Urban-1 | €800,000 | 15,000 units | 0.8 hrs |
| Urban-2 | €850,000 | 12,000 units | 0.9 hrs |
| Suburban-1 | €600,000 | 18,000 units | 1.2 hrs |
| Suburban-2 | €650,000 | 16,000 units | 1.1 hrs |
| Industrial-1 | €500,000 | 25,000 units | 1.8 hrs |

Zone demand ranges from 850 to 1,800 units. Vehicle cost: €50,000/vehicle; 1 vehicle required per 3,000 units of served demand.

---

## The Learning Loop

The app gets smarter with use. Each session captures how you phrase logistics trade-offs and which results you find valuable — that signal feeds directly into the next session's system prompt.

### How the flywheel works

```
Session starts
  └─ Load up to 5 (query → params) pairs from well-rated past sessions
  └─ Inject them as few-shot examples into Claude's system prompt

Each turn
  └─ You ask a question in plain English
  └─ Claude infers solver parameters, runs the MILP, shows results
  └─ (query, inferred_params, solver_outcome) logged to JSONL

Session ends  [type: quit]
  └─ "How useful was this session? [1 / 2 / 3]"  ← one keypress
  └─ Rating saved — labels every query in the session

Next session starts smarter ↑
```

### What gets captured

| Signal | Purpose |
|--------|---------|
| `query_text` | Vocabulary you actually use |
| `inferred_params` | How natural language maps to solver parameters |
| `solver_outcome` | Cost, delivery time, coverage, feasibility per run |
| `agent_turn_count` | How much reasoning Claude needed |
| `session_rating` | Marks the whole session as useful (2–3) or not (1) |

### Rating gate

Only interactions from sessions rated **2 or 3** become few-shot examples. Sessions rated 1 are stored but never used. Sessions closed without a rating are stored but also excluded — typing `quit` and entering a rating is the only way to contribute to the learning loop.

### Storage

All data is stored inside the project under `data/`:

```
data/
├── interactions.jsonl    # Append-only primary store — one JSON record per line
└── interactions.db       # SQLite query layer — rebuilt from JSONL at each startup
```

The JSONL file is the durable asset. The SQLite database is disposable: delete it and it rebuilds automatically on the next run.

### When does it noticeably improve?

| Rated sessions | Effect |
|----------------|--------|
| 1 | First few-shot examples injected — improvement begins |
| 3–5 | Prompt reaches full 5-example capacity |
| 20+ | Consistent coverage constraint inference from ambiguous phrasing |
| 50–75 | Measurable outperformance vs. a generic Claude deployment on this domain's vocabulary |

The learning stack adds no new dependencies — it uses only Python standard library modules (`sqlite3`, `json`, `uuid`, `datetime`, `pathlib`). All logging errors are caught silently; the app never fails because of the logger.

---

## Project Structure

```
logistics-agent-learning-model01a/
├── main.py                      # Entry point, interaction loop, learning wiring
├── requirements.txt
├── README.md
├── data/                        # Runtime data — gitignored
│   ├── interactions.jsonl       # Append-only interaction log
│   └── interactions.db          # SQLite query layer (auto-rebuilt)
├── src/
│   ├── models.py                # Pydantic data contracts
│   ├── solver.py                # Pyomo + HiGHS MILP solver
│   ├── claude_agent.py          # Anthropic SDK agentic loop
│   ├── cli.py                   # Rich terminal display
│   └── learning/
│       ├── logger.py            # JSONL write + SQLite sync + example retrieval
│       └── prompt_builder.py    # System prompt + few-shot injection
└── docs/
    └── loop-implementation.md   
```
---

## Acknowledgments

This project was inspired by and built with reference to [Optimization Agents — Supply Chain & Logistics](https://github.com/zishanyusuf/Optimization-Agents-Supply-Chain-Logistics) by [@zishanyusuf](https://github.com/zishanyusuf).

The original repository provided the foundational approach of combining an AI agent with a MILP solver for logistics network optimization. This project extends that concept in a different direction: replacing the original interface with a Rich-based CLI and adding a **learning loop** — a session logging and few-shot injection system that allows the agent to improve its parameter inference from rated user interactions over time.

All learning loop components (`src/learning/`), the interaction logging schema, the session rating mechanism, and the dynamic system prompt construction are original additions developed independently from the reference project.
