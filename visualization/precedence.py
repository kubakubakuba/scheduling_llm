import networkx as nx
import plotly.graph_objects as go
from collections import defaultdict

def build_precedence_graph(jobs, predecessors, orders):
	G = nx.DiGraph()
	for j in jobs:
		G.add_node(j)
		
	parents_of = defaultdict(list)
	for pred, succs in predecessors.items():
		for succ in succs:
			G.add_edge(pred, succ)
			parents_of[succ].append(pred)

	for j in G.nodes:
		G.nodes[j]['layer'] = 0
		
	for node in nx.topological_sort(G):
		for child in G.successors(node):
			G.nodes[child]['layer'] = max(G.nodes[child].get('layer', 0), G.nodes[node]['layer'] + 1)

	job_to_order = {}
	order_names = {}
	for o in orders:
		sink = o['sink_job']
		order_names[sink] = o.get('component_id', f"Order_{sink}")
		queue = [sink]
		while queue:
			curr = queue.pop(0)
			if curr not in job_to_order:
				job_to_order[curr] = sink
				queue.extend(parents_of.get(curr, []))

	unassigned = [n for n in G.nodes if n not in job_to_order]
	orders_list = [o['sink_job'] for o in orders]
	
	if unassigned:
		orders_list.append("Unassigned")
		order_names["Unassigned"] = "Unassigned Jobs"
		for n in unassigned:
			job_to_order[n] = "Unassigned"

	pos = {}
	x_spacing = 5 
	order_y_spacing = 8
	node_y_spacing = 1.5

	for o_idx, sink in enumerate(orders_list):
		y_base = -o_idx * order_y_spacing
		order_nodes = [n for n in G.nodes if job_to_order.get(n) == sink]
		
		layer_dict = defaultdict(list)
		for n in order_nodes:
			layer_dict[G.nodes[n]['layer']].append(n)
			
		for layer, nodes_in_layer in layer_dict.items():
			num_nodes = len(nodes_in_layer)
			offset = (num_nodes - 1) * node_y_spacing / 2.0
			for i, n in enumerate(nodes_in_layer):
				pos[n] = (layer * x_spacing, y_base + offset - (i * node_y_spacing))

	sink_jobs = {o['sink_job']: o for o in orders}

	edge_x = []
	edge_y = []
	for edge in G.edges():
		x0, y0 = pos[edge[0]]
		x1, y1 = pos[edge[1]]
		edge_x.extend([x0, x1, None])
		edge_y.extend([y0, y1, None])

	node_x = []
	node_y = []
	node_text = []
	node_color = []
	hover_text = []

	for node in G.nodes():
		x, y = pos[node]
		node_x.append(x)
		node_y.append(y)
		node_text.append(str(node))
		
		if node in sink_jobs:
			node_color.append("#ff7f0e")
			hover_text.append(f"<b>Sink job {node}</b><br>Due date: {sink_jobs[node]['due_date']}<br>Weight: {sink_jobs[node]['weight']}")
		else:
			node_color.append("#1f77b4")
			hover_text.append(f"Job {node}")

	fig = go.Figure()
	order_boxes = {}
	
	for node, (x, y) in pos.items():
		sink = job_to_order.get(node)
		if sink is not None:
			if sink not in order_boxes:
				order_boxes[sink] = {'min_x': x, 'max_x': x, 'min_y': y, 'max_y': y}
			else:
				order_boxes[sink]['min_x'] = min(order_boxes[sink]['min_x'], x)
				order_boxes[sink]['max_x'] = max(order_boxes[sink]['max_x'], x)
				order_boxes[sink]['min_y'] = min(order_boxes[sink]['min_y'], y)
				order_boxes[sink]['max_y'] = max(order_boxes[sink]['max_y'], y)

	for sink, box in order_boxes.items():
		padding_x = 1.0
		padding_y = 1.0
		order_label = order_names.get(sink, f"Order")
		label_text = f"{order_label}" if sink == "Unassigned" else f"{order_label}"

		fig.add_shape(
			type="rect",
			x0=box['min_x'] - padding_x, x1=box['max_x'] + padding_x,
			y0=box['min_y'] - padding_y, y1=box['max_y'] + padding_y,
			fillcolor="rgba(150, 150, 150, 0.1)",
			line=dict(color="gray", width=2, dash="dot"),
			layer="below"
		)
		fig.add_annotation(
			x=box['min_x'] - padding_x, 
			y=box['max_y'] + padding_y,
			text=label_text,
			showarrow=False,
			xanchor="left",
			yanchor="bottom",
			font=dict(size=14, color="black", weight="bold")
		)

	fig.add_trace(go.Scatter(
		x=edge_x, y=edge_y, 
		line=dict(width=1, color='#888'), 
		mode='lines', 
		hoverinfo='none'
	))
	
	fig.add_trace(go.Scatter(
		x=node_x, y=node_y, 
		mode='markers+text',
		text=node_text, 
		textposition="middle center",
		textfont=dict(color="white"),
		marker=dict(size=30, color=node_color, line=dict(width=2, color='black')),
		hovertext=hover_text, 
		hoverinfo='text'
	))

	fig.update_layout(
		title="Precedence graph by orders", 
		showlegend=False, 
		xaxis=dict(visible=False), 
		yaxis=dict(visible=False), 
		template="plotly_white",
		height=300 * len(orders_list)
	)

	return fig