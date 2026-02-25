import os
import json
from typing import Any

import anthropic

from src.learning.prompt_builder import BASE_SYSTEM_PROMPT
from src.models import SolverParams
from src.solver import run_solver, SolverError


MAX_AGENTIC_ITERATIONS = 10


LOGISTICS_TOOL_DEFINITION = {
    "name": "logistics_solver",
    "description": (
        "Runs Mixed-Integer Programming (MILP) to optimize a delivery network: "
        "warehouse locations, zone assignments, and vehicle fleet sizing across "
        "5 warehouses and 20 delivery zones. "
        "Purpose: Decides which warehouses to open, assigns delivery zones to warehouses, "
        "and determines optimal fleet size to optimize logistics objectives under constraints."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "objective": {
                "type": "string",
                "enum": ["Total Cost", "Delivery Time", "Fleet Utilization", "Service Coverage"],
                "description": "Optimization objective to use.",
            },
            "max_delivery_time": {
                "type": ["number", "null"],
                "description": "Maximum acceptable delivery time in hours (e.g. 2.0). Null to ignore.",
            },
            "max_vehicles_per_warehouse": {
                "type": ["integer", "null"],
                "description": "Maximum number of vehicles per warehouse. Null to ignore.",
            },
            "min_service_coverage": {
                "type": ["number", "null"],
                "description": "Minimum fraction of zones to serve (0.0–1.0, e.g. 0.9 for 90%). Null to ignore.",
            },
        },
        "required": ["objective"],
    },
}


class ClaudeAgent:
    def __init__(self, system_prompt: str | None = None) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY is not set. "
                "Set it with: set ANTHROPIC_API_KEY=your_key_here"
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._history: list[dict] = []
        self.last_tool_results: list[dict] = []
        self._system_prompt: str = system_prompt if system_prompt is not None else BASE_SYSTEM_PROMPT
        self._last_turn_count: int = 0

    @property
    def turn_count(self) -> int:
        """Number of agentic iterations in the most recent chat() call."""
        return self._last_turn_count

    def chat(self, user_message: str) -> str:
        """Send a user message and run the agentic loop. Returns Claude's final text response."""
        self._history.append({"role": "user", "content": user_message})
        self.last_tool_results = []
        self._last_turn_count = 0

        for _ in range(MAX_AGENTIC_ITERATIONS):
            self._last_turn_count += 1
            response = self._client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                system=self._system_prompt,
                tools=[LOGISTICS_TOOL_DEFINITION],
                messages=self._history,
            )

            # Append assistant turn to history
            self._history.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "end_turn":
                return self._extract_text(response.content)

            if response.stop_reason == "tool_use":
                tool_results = self._execute_tool_calls(response.content)
                self._history.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason — return whatever text we have
                return self._extract_text(response.content)

        return "Maximum reasoning iterations reached. Please try a more specific question."

    def clear_history(self) -> None:
        """Reset conversation history."""
        self._history = []
        self.last_tool_results = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_tool_calls(self, content: list[Any]) -> list[dict]:
        """Execute all tool-use blocks and return a tool_result message."""
        tool_result_content = []

        for block in content:
            if block.type != "tool_use":
                continue

            tool_input = block.input
            try:
                params = SolverParams(
                    objective=tool_input.get("objective", "Total Cost"),
                    max_delivery_time=tool_input.get("max_delivery_time"),
                    max_vehicles_per_warehouse=tool_input.get("max_vehicles_per_warehouse"),
                    min_service_coverage=tool_input.get("min_service_coverage"),
                )
                solver_result = run_solver(params)

                # Store for main.py to render
                self.last_tool_results.append({
                    "tool_use_id": block.id,
                    "result": solver_result,
                })

                result_json = solver_result.model_dump_json(indent=2)
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_json,
                })

            except SolverError as exc:
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "is_error": True,
                    "content": f"Solver error: {exc}",
                })
            except Exception as exc:
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "is_error": True,
                    "content": f"Unexpected error: {exc}",
                })

        return tool_result_content

    @staticmethod
    def _extract_text(content: list[Any]) -> str:
        """Extract all text blocks from a content list."""
        parts = [block.text for block in content if hasattr(block, "text")]
        return "\n".join(parts).strip()
