"""
Logistics Optimizer CLI — entry point.

Run:
    python main.py

Requirements:
    pip install -r requirements.txt
    ANTHROPIC_API_KEY must be set in the environment.
"""
import traceback

from src.cli import (
    confirm_clear_history,
    prompt_session_rating,
    prompt_user_message,
    show_cancellation,
    show_claude_response,
    show_error,
    show_help,
    show_model_info,
    show_thinking,
    show_warning,
    show_welcome,
)
from src.learning.logger import InteractionLogger
from src.learning.prompt_builder import build_system_prompt
from src.solver import SolverError


def main() -> None:
    try:  # Layer 3: outer catch-all
        show_welcome()
        show_model_info()

        # Import here so a missing API key surfaces immediately
        from src.claude_agent import ClaudeAgent

        # --- Learning-loop setup ---
        logger = InteractionLogger()
        session_id = logger.new_session()
        few_shot_examples = logger.get_few_shot_examples()
        dynamic_prompt = build_system_prompt(few_shot_examples)

        try:
            agent = ClaudeAgent(system_prompt=dynamic_prompt)
        except EnvironmentError as exc:
            show_error(str(exc))
            return

        turn_index = 0
        total_solver_calls = 0

        while True:
            try:  # Layer 2: per-step
                user_input = prompt_user_message().strip()

                if not user_input:
                    continue

                if user_input.lower() in {"quit", "exit", "q"}:
                    rating = prompt_session_rating()
                    if rating is not None:
                        logger.log_session_rating(
                            session_id, rating, turn_index, total_solver_calls
                        )
                    show_cancellation()
                    break

                if user_input.lower() in {"help", "h", "?"}:
                    show_help()
                    continue

                if user_input.lower() == "clear":
                    if confirm_clear_history():
                        agent.clear_history()
                        show_warning("Conversation history cleared.")
                    continue

                with show_thinking() as progress:
                    progress.add_task("Reasoning...", total=None)
                    response = agent.chat(user_input)

                show_claude_response(response)

                # --- Log this interaction ---
                inferred_params: dict = {}
                if agent.last_tool_results:
                    inferred_params = (
                        agent.last_tool_results[0]["result"].params.model_dump()
                    )

                solver_calls = [
                    {
                        "scenario_name": tr["result"].scenario_name,
                        "is_feasible": tr["result"].output.is_feasible,
                        "total_cost": tr["result"].output.total_cost,
                        "avg_delivery_time": tr["result"].output.avg_delivery_time,
                        "service_coverage": tr["result"].output.service_coverage,
                        "params": tr["result"].params.model_dump(),
                    }
                    for tr in agent.last_tool_results
                ]

                logger.log_interaction(
                    session_id=session_id,
                    turn_index=turn_index,
                    query_text=user_input,
                    inferred_params=inferred_params,
                    solver_calls=solver_calls,
                    agent_turn_count=agent.turn_count,
                )

                total_solver_calls += len(agent.last_tool_results)
                turn_index += 1

            except KeyboardInterrupt:
                rating = prompt_session_rating()
                if rating is not None:
                    logger.log_session_rating(
                        session_id, rating, turn_index, total_solver_calls
                    )
                show_cancellation()
                break
            except SolverError as exc:
                show_error(str(exc))
                continue
            except Exception as exc:  # noqa: BLE001
                show_error(str(exc))
                continue

    except KeyboardInterrupt:
        show_cancellation()
    except Exception as exc:  # noqa: BLE001
        show_error(str(exc))
        traceback.print_exc()


if __name__ == "__main__":
    main()
