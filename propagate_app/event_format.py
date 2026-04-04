from __future__ import annotations


def format_event_reply(event: dict) -> str:
    """Format a ZMQ event dict into a human-readable string.

    Shared by the Telegram bot and the interactive shell.
    """
    event_type = event.get("event", "unknown")
    if event_type == "command_failed":
        command = event.get("command", "unknown")
        message = event.get("message", "Command failed.")
        return f"Command /{command} failed: {message}"
    if event_type == "waiting_for_signal":
        signal_name = event.get("signal", "unknown")
        execution = event.get("execution", "")
        if execution:
            return f"Waiting for signal '{signal_name}' (execution '{execution}')."
        return f"Waiting for signal '{signal_name}'."
    if event_type == "signal_received":
        signal_name = event.get("signal", "unknown")
        execution = event.get("execution", "")
        if execution:
            return f"Signal '{signal_name}' received — resuming execution '{execution}'."
        return f"Signal '{signal_name}' received — resuming."
    if event_type == "pr_created":
        execution = event.get("execution", "unknown")
        pr_url = event.get("pr_url", "")
        return f"PR created for '{execution}':\n{pr_url}"
    if event_type == "pr_updated":
        execution = event.get("execution", "unknown")
        pr_url = event.get("pr_url", "")
        return f"PR updated for '{execution}':\n{pr_url}"
    if event_type == "clarification_requested":
        question = event.get("question", "No question provided.")
        request_id = event.get("request_id", "unknown")
        execution = event.get("metadata", {}).get("execution", "unknown")
        return f"Clarification requested in execution '{execution}' (id: {request_id}):\n{question}\n\n(Please reply to this message with your answer)"
    if event_type in ("run_completed", "run_failed"):
        signal_type = event.get("signal_type", "unknown")
        messages = event.get("messages") or []
        lines = [f"Run {'completed' if event_type == 'run_completed' else 'failed'} for signal '{signal_type}'."]
        if messages:
            lines.append("")
            for msg in messages:
                lines.append(msg)
        return "\n".join(lines)
    return f"Event: {event_type}"
