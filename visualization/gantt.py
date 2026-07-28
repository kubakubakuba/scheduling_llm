import plotly.graph_objects as go
from plotly.subplots import make_subplots

def build_resource_gantt_figure(schedule, durations, jobs, requests, resources, shifts):
	max_end = max((e for _, e in schedule.values() if e is not None), default=0)
	if max_end == 0:
		fig = go.Figure()
		fig.add_annotation(text="No schedule data", x=0.5, y=0.5, showarrow=False)
		return fig

	fig = make_subplots(
		rows=len(resources), cols=1, 
		shared_xaxes=True, 
		subplot_titles=[f"Resource {r}" for r in resources]
	)

	for idx, r in enumerate(resources):
		row = idx + 1
		placed_rects = []

		r_jobs = [j for j in jobs if requests.get((j, r), 0) > 0 and schedule.get(j) is not None and schedule[j][0] is not None]
		r_jobs.sort(key=lambda j: (-requests.get((j, r), 0), schedule[j][0]))

		for j in r_jobs:
			s, e = schedule[j]
			amount = requests[(j, r)]
			if s == e:
				continue

			y_base = 0
			while True:
				overlap = False
				for rs, re, ry_bot, ry_top in placed_rects:
					if max(s, rs) < min(e, re):
						if max(y_base, ry_bot) < min(y_base + amount, ry_top):
							overlap = True
							y_base = ry_top
							break
				if not overlap:
					break
			
			placed_rects.append((s, e, y_base, y_base + amount))

			fig.add_trace(go.Scatter(
				x=[s, e, e, s, s],
				y=[y_base, y_base, y_base + amount, y_base + amount, y_base],
				fill="toself",
				mode="lines",
				line=dict(color="black", width=1),
				fillcolor="#1f77b4",
				text=f"Job {j}<br>Req: {amount}",
				hoverinfo="text",
				showlegend=False
			), row=row, col=1)

			fig.add_annotation(
				x=(s + e) / 2, 
				y=y_base + (amount / 2),
				text=str(j),
				showarrow=False,
				font=dict(color="white"),
				row=row, col=1
			)

		cap_x = []
		cap_y = []
		for start, end, c in shifts.get(r, []):
			if start > max_end:
				continue
			end = min(end, max_end)
			cap_x.extend([start, end, None])
			cap_y.extend([c, c, None])

		fig.add_trace(go.Scatter(
			x=cap_x, y=cap_y, 
			mode="lines",
			line=dict(color="red", dash="dash", shape="hv"),
			name=f"Capacity {r}", 
			showlegend=False
		), row=row, col=1)

	fig.update_layout(
		height=300 * len(resources), 
		title="Resource consumption Gantt chart", 
		template="plotly_white",
		xaxis_title="Time"
	)

	return fig