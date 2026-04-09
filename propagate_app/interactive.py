"""Interactive interrupt-and-resume session handling."""

from __future__ import annotations

from .constants import LOGGER
from .errors import AgentInterrupted
from .processes import build_interactive_agent_command, run_interactive_agent

ACTION_RERUN = "rerun"
ACTION_SKIP = "skip"
ACTION_ABORT = "abort"


def handle_agent_interrupt(exc: AgentInterrupted) -> str:
    """Handle an agent interrupt: launch interactive session, return action choice."""
    print(f"\n--- Interrupted during execution '{exc.execution_name}', task '{exc.task_id}'. ---")
    print(f"Launching interactive agent session in {exc.working_dir}...\n")

    interactive_cmd = build_interactive_agent_command(exc.agent_command)
    LOGGER.debug("Starting interactive session: %s", interactive_cmd)

    run_interactive_agent(interactive_cmd, exc.working_dir)

    print("\n--- Interactive session ended. ---")
    return prompt_resume_action()


def prompt_resume_action() -> str:
    """Ask the user what to do after the interactive session."""
    while True:
        try:
            choice = input("[R]erun task / [S]kip to next / [A]bort? ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ACTION_ABORT
        if choice in ("r", "rerun"):
            return ACTION_RERUN
        if choice in ("s", "skip"):
            return ACTION_SKIP
        if choice in ("a", "abort"):
            return ACTION_ABORT
        print("Please enter R, S, or A.")
