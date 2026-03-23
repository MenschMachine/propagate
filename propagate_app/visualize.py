"""Visualize the execution DAG as a text diagram."""

from pathlib import Path

from .config_load import load_config
from .graph import build_execution_graph_adjacency


def visualize_command(config_value: str) -> int:
    """Load config and output execution flow diagram."""
    config_path = Path(config_value).expanduser()
    config = load_config(config_path)

    # Build adjacency: source -> [targets]
    adjacency = build_execution_graph_adjacency(config.executions, config.propagation_triggers)

    # Build reverse adjacency: target -> [sources]
    reverse_adj: dict[str, list[str]] = {name: [] for name in config.executions}
    for source, targets in adjacency.items():
        for target in targets:
            reverse_adj[target].append(source)

    # Compute incoming edges per node
    depends_on_edges: dict[str, list[str]] = {name: [] for name in config.executions}
    for execution in config.executions.values():
        for dep in execution.depends_on:
            depends_on_edges[execution.name].append(dep)

    # Collect trigger edges by source
    trigger_edges: dict[str, list[tuple[str, str | None]]] = {name: [] for name in config.executions}
    for trigger in config.propagation_triggers:
        trigger_edges[trigger.after].append((trigger.run, trigger.on_signal))

    # Topological sort using Kahn's algorithm
    in_degree = {name: len(reverse_adj[name]) for name in config.executions}
    queue = [name for name, deg in in_degree.items() if deg == 0]
    topo_order: list[str] = []
    while queue:
        node = queue.pop(0)
        topo_order.append(node)
        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    # If not all nodes are in topo_order, there's a cycle (shouldn't happen)
    for name in config.executions:
        if name not in topo_order:
            topo_order.append(name)

    # Generate output
    lines: list[str] = []
    lines.append(f"Execution Flow: {config_path}")
    lines.append("=" * (14 + len(str(config_path))))

    for i, name in enumerate(topo_order, 1):
        deps = depends_on_edges[name]
        triggers = trigger_edges[name]
        execution = config.executions[name]

        lines.append(f"{i}. {name}")
        for dep in deps:
            lines.append(f"   -> depends on: {dep}")
        for target, signal in triggers:
            if signal:
                lines.append(f"   -> triggers: {target} (on_signal: {signal})")
            else:
                lines.append(f"   -> triggers: {target}")

        # Show sub-task internal flow
        _add_subtask_flow(lines, execution)

    print("\n".join(lines))
    return 0


def _add_subtask_flow(lines: list[str], execution) -> None:
    """Add sub-task internal flow details to lines."""
    sub_tasks = execution.sub_tasks
    if not sub_tasks:
        return

    for st in sub_tasks:
        indent = "   "
        details: list[str] = []

        # Conditional execution
        if st.when:
            details.append(f"[when: {st.when}]")

        # Direct goto
        if st.goto:
            details.append(f"-> goto: {st.goto}")

        # Wait for signal with routes
        if st.wait_for_signal:
            sig_details = f"wait_for_signal: {st.wait_for_signal}"
            if st.routes:
                for route in st.routes:
                    if route.goto:
                        sig_details += f" -> {route.goto}"
                    elif route.continue_flow:
                        sig_details += " -> continue"
            details.append(sig_details)

        if details:
            lines.append(f"{indent}  {st.task_id}: {' '.join(details)}")

    # Check for unreachable tasks (after a goto that doesn't return)
    gotos = {st.task_id: st.goto for st in sub_tasks if st.goto}
    wait_signals = {st.task_id for st in sub_tasks if st.wait_for_signal}
    if gotos or wait_signals:
        lines.append(f"{indent}  (internal routing present)")

