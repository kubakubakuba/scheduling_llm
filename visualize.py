import os
import json
import typer
import dash
from dash import dcc, html
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from solver import MRCPSP_solver

app_typer = typer.Typer(help="Visualize the schedule of a JSON instance using Dash/Plotly.")


def load_instance(filepath: str):
	with open(filepath, 'r', encoding='utf-8') as f:
		data = json.load(f)
	durations = {int(k): v for k, v in data["durations"].items()}
	predecessors = {int(k): v for k, v in data["predecessors"].items()}
	requests = {(req["job"], req["resource"]): req["amount"] for req in data["requests"]}
	return {
		"jobs": data["jobs"],
		"durations": durations,
		"predecessors": predecessors,
		"resources": data["resources"],
		"requests": requests,
		"shifts": data["shifts"],
		"orders": data["orders"]
	}


def get_primary_resource(job, requests, resources):
	max_amount = 0
	primary = None
	for r in resources:
		amount = requests.get((job, r), 0)
		if amount > max_amount:
			max_amount = amount
			primary = r
	return primary


def build_gantt_figure(schedule, durations, jobs, requests):
	rows = []
	for j in jobs:
		dur = durations.get(j, 0)
		if dur <= 0:
			continue
		s, e = schedule.get(j, (None, None))
		if s is None or e is None:
			continue
		
		req_items = [f"{r}: {amt}" for (job, r), amt in requests.items() if job == j and amt > 0]
		req_str = ", ".join(req_items) if req_items else "None"
		rows.append({
			"Job": f"Job {j}",
			"Start": s,
			"Finish": e,
			"Duration": e - s,
			"Resources": req_str
		})

	if not rows:
		fig = go.Figure()
		fig.add_annotation(text="No jobs with positive duration found in schedule",
						x=0.5, y=0.5, showarrow=False)
		fig.update_layout(title="Job Schedule (Gantt Chart)", template="plotly_white")
		return fig

	df = pd.DataFrame(rows)
	fig = go.Figure()
	for _, row in df.iterrows():
		fig.add_trace(go.Bar(
			x=[row["Duration"]],
			y=[row["Job"]],
			orientation='h',
			base=[row["Start"]],
			marker_color="#1f77b4",
			text=[row["Duration"]],
			textposition='inside',
			insidetextanchor='middle',
			hovertemplate=(
				f"{row['Job']}<br>"
				"Start: %{base}<br>"
				"Finish: %{x}<br>"
				"Duration: %{text}<br>"
				f"Resources: {row['Resources']}<extra></extra>"
			)
		))
	fig.update_layout(
		title="Gantt chart",
		xaxis_title="Time",
		yaxis_title="Jobs",
		yaxis=dict(autorange="reversed"),
		barmode='relative',
		template="plotly_white"
	)
	return fig


def build_resource_usage_figure(schedule, requests, resources, shifts):
	max_end = max((e for _, e in schedule.values() if e is not None), default=0)
	if max_end == 0:
		fig = go.Figure()
		fig.add_annotation(text="No schedule data", x=0.5, y=0.5, showarrow=False)
		fig.update_layout(title="Resource Usage over Time", template="plotly_white")
		return fig

	time_points = list(range(max_end + 1))

	#usage per resource
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

	#capacity profile per resource
	capacity_data = {}
	for r in resources:
		cap = [0] * (max_end + 1)
		for start, end, c in shifts.get(r, []):
			for t in range(start, min(end, max_end + 1)):
				cap[t] = c
		capacity_data[r] = cap

	fig = go.Figure()

	#usage traces
	for r in resources:
		fig.add_trace(go.Scatter(
			x=time_points,
			y=resource_data[r],
			mode='lines+markers',
			name=f"Usage {r}",
			line=dict(shape='hv')
		))

	#capacity traces
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
		title="Resource usage and capacity over time",
		xaxis_title="Time",
		yaxis_title="Resource units",
		template="plotly_white"
	)
	return fig


@app_typer.command()
def visualize(
	path: str = typer.Argument(..., help="Path to a JSON instance file"),
	time_limit: int = typer.Option(60, help="Solver time limit in seconds"),
	log_output: bool = typer.Option(False, help="Show CP Optimizer logs")
):
	"""
	Loads the instance, solves it, and launches a Dash web app showing the schedule.
	"""
	if not os.path.isfile(path):
		typer.echo(f"File not found: {path}")
		raise typer.Exit()

	typer.echo(f"Loading instance: {path}")
	instance_data = load_instance(path)

	resources = instance_data["resources"]
	requests = instance_data["requests"]
	primary_resources = {}
	for j in instance_data["jobs"]:
		prim = get_primary_resource(j, requests, resources)
		if prim is not None:
			primary_resources[j] = prim

	typer.echo("Solving...")
	solver = MRCPSP_solver(**instance_data)
	solver.init_model()
	obj_val = solver.solve(time_limit=time_limit, log_output=log_output)
	schedule = solver.get_schedule()

	if schedule is None:
		typer.echo("No feasible solution found.")
		raise typer.Exit()
	
	max_time = max((e for _, e in schedule.values() if e is not None), default=0)

	gantt_fig = build_gantt_figure(
		schedule, instance_data["durations"], instance_data["jobs"],
		instance_data["requests"]   # if you added the hover enhancement
	)

	resource_fig = build_resource_usage_figure(
		schedule, instance_data["requests"], instance_data["resources"], instance_data["shifts"]
	)

	gantt_fig.update_xaxes(range=[0, max_time])
	resource_fig.update_xaxes(range=[0, max_time])


	typer.echo(f"Objective (weighted tardiness): {obj_val}")

	typer.echo("\nSchedule for jobs with positive duration:")
	for j, dur in instance_data["durations"].items():
		if dur > 0:
			s, e = schedule.get(j, (None, None))
			typer.echo(f"  Job {j}: start={s}, end={e}, duration={dur}")

	app = dash.Dash(__name__)
	app.layout = html.Div([
		html.H1(f"objective: {obj_val}", style={"textAlign": "center"}),
		dcc.Graph(id="gantt", figure=gantt_fig),
		dcc.Graph(id="resources", figure=resource_fig),
	])

	typer.echo("Starting Dash server at http://127.0.0.1:8050/")
	app.run(debug=False)


if __name__ == "__main__":
	app_typer()