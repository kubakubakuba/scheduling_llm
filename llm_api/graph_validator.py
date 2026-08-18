import networkx as nx

def validate_precedence_graph(instance: dict) -> None:
    graph = nx.DiGraph()
    graph.add_nodes_from(instance["jobs"])

    for successor_str, predecessors in instance["predecessors"].items():
        successor = int(successor_str)

        if successor not in graph:
            raise ValueError(f"Unknown successor job {successor}")

        for predecessor in predecessors:
            if predecessor not in graph:
                raise ValueError(f"Unknown predecessor job {predecessor}")

            if predecessor == successor:
                raise ValueError(
                    f"Job {successor} cannot precede itself."
                )

            graph.add_edge(predecessor, successor)

    try:
        cycle = nx.find_cycle(graph, orientation="original")
    except nx.NetworkXNoCycle:
        return

    cycle_nodes = [edge[0] for edge in cycle]
    cycle_nodes.append(cycle[0][0])

    cycle_text = " -> ".join(map(str, cycle_nodes))
    raise ValueError(f"Precedence cycle detected: {cycle_text}")
