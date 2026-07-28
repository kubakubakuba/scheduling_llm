import plotly.graph_objects as go

def build_resource_usage_figure(schedule, requests, resources, shifts):
	max_end = max((e for _, e in schedule.values() if e is not None), default=0)
	if max_end == 0:
		fig = go.Figure()
		fig.add_annotation(text="No schedule data", x=0.5, y=0.5, showarrow=False)
		fig.update_layout(title="Resource usage over time", template="plotly_white")
		return fig

	time_points = list(range(max_end + 1))
	resource_data = {}
	
	for r in resources:
		usage = [0] * (max_end + 1)
		for (j, res), amount in requests.items():
			if res != r:
				continue
			s, e = schedule.get(j, (None, None))
			if s is None or e is None:
				continue
			for t in range(s, min(e, max_end + 1)):
				usage[t] += amount
		resource_data[r] = usage

	capacity_data = {}
	for r in resources:
		cap = [0] * (max_end + 1)
		for start, end, c in shifts.get(r, []):
			for t in range(start, min(end, max_end + 1)):
				cap[t] = c
		capacity_data[r] = cap

	fig = go.Figure()
	for r in resources:
		fig.add_trace(go.Scatter(
			x=time_points,
			y=resource_data[r],
			mode='lines+markers',
			name=f"Usage {r}",
			line=dict(shape='hv')
		))

	for r in resources:
		fig.add_trace(go.Scatter(
			x=time_points,
			y=capacity_data[r],
			mode='lines',
			name=f"Capacity {r}",
			line=dict(shape='hv', dash='dash', color='red'),
			showlegend=True
		))

	fig.update_layout(
		title="Cumulative resource usage vs. capacity limit",
		xaxis_title="Time",
		yaxis_title="Resource units",
		template="plotly_white"
	)
	return fig