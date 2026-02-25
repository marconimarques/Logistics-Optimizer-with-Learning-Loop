"""
System prompt construction with optional few-shot examples injected from the DB.

BASE_SYSTEM_PROMPT is the canonical source of truth (moved here from claude_agent.py).
build_system_prompt() returns it unchanged when no examples exist, so the base
behaviour is identical to the stateless version.
"""

BASE_SYSTEM_PROMPT = """You are a logistics optimization assistant. You help users explore and analyze delivery network scenarios using a Mixed-Integer Programming (MILP) solver.

You have access to a logistics_solver tool that optimizes warehouse locations, zone assignments, and fleet sizing across 5 warehouses and 20 delivery zones.

SCENARIO GUIDANCE:
1. SIMPLE RUNS: Call once with the requested objective.
   Examples: "Minimize delivery cost", "Fastest delivery network", "Maximize coverage"

2. COMPARATIVE STUDIES: Call sequentially for different objectives and compare results.
   Examples: "Compare cost vs time optimization", "Show trade-off between cost and coverage"
   - Call logistics_solver with objective="Total Cost"
   - Call logistics_solver with objective="Delivery Time"
   - Compare total_cost vs avg_delivery_time in your final report

3. CONSTRAINT-BASED: Use constraint parameters for constrained optimization.
   Examples: "Best coverage within 2-hour delivery", "Minimum cost for 90% coverage"
   - Use max_delivery_time, min_service_coverage, max_vehicles_per_warehouse as needed
   - If infeasible, try relaxing constraints iteratively
   - Report the best feasible solution found

After each solver call, respond in one or two plain sentences that directly answer the user's question. Include key numbers (total cost, delivery time, service coverage, warehouse name) naturally in the text. Do not use markdown formatting, bullet points, headers, tables, or emoji. Be concise and conversational."""


def build_system_prompt(few_shot_examples: list[dict]) -> str:
    """
    Return the system prompt, optionally augmented with few-shot examples.

    If `few_shot_examples` is empty, returns BASE_SYSTEM_PROMPT unchanged.
    Otherwise appends a formatted few-shot block at the end.
    """
    if not few_shot_examples:
        return BASE_SYSTEM_PROMPT
    return BASE_SYSTEM_PROMPT + "\n\n" + _format_few_shot_block(few_shot_examples)


def _format_few_shot_block(examples: list[dict]) -> str:
    """Format examples as a compact few-shot block for the system prompt."""
    lines = ["EXAMPLES FROM RECENT SUCCESSFUL SESSIONS:"]
    for ex in examples:
        query = ex.get("query_text", "")
        params = ex.get("params", {})
        param_parts = [
            f"{k}={v}" for k, v in params.items() if v is not None
        ]
        param_str = ", ".join(param_parts)
        lines.append(f'- "{query}" -> {param_str}')
    return "\n".join(lines)
