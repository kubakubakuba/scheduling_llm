import os
import typer
import dash
from dash import dcc, html

from solver import MRCPSP_solver
from visualization.utils import load_instance
from visualization.gantt import build_resource_gantt_figure
from visualization.usage import build_resource_usage_figure
from visualization.precedence import build_precedence_graph

app_typer = typer.Typer(help="Visualize the schedule of a JSON instance using Dash/Plotly.")

@app_typer.command()
def visualize(
	path: str = typer.Argument(..., help="Path to a JSON instance file"),
	time_limit: int = typer.Option(60, help="Solver time limit in seconds"),
	log_output: bool = typer.Option(False, help="Show CP Optimizer logs")
):
	if not os.path.isfile(path):
		typer.echo(f"File not found: {path}")
		raise typer.Exit()

	typer.echo(f"Loading instance: {path}")
	instance_data = load_instance(path)

	typer.echo("Solving...")
	solver = MRCPSP_solver(**instance_data)
	solver.init_model()
	obj_val = solver.solve(time_limit=time_limit, log_output=log_output)
	schedule = solver.get_schedule()

	if schedule is None:
		typer.echo("No feasible solution found.")
		raise typer.Exit()

	gantt_fig = build_resource_gantt_figure(
		schedule, instance_data["durations"], instance_data["jobs"],
		instance_data["requests"], instance_data["resources"], instance_data["shifts"]
	)
	
	usage_fig = build_resource_usage_figure(
		schedule, instance_data["requests"], instance_data["resources"], instance_data["shifts"]
	)

	precedence_fig = build_precedence_graph(
		instance_data["jobs"], instance_data["predecessors"], instance_data["orders"]
	)

	typer.echo(f"Objective: {obj_val}")

	app = dash.Dash(__name__)
	
	app.layout = html.Div([
		html.H1(f"Weighted tardiness: {obj_val}", style={"textAlign": "center", "fontFamily": "sans-serif"}),
		dcc.Tabs([
			dcc.Tab(label='Resource Gantt Chart', children=[
				dcc.Graph(id="gantt", figure=gantt_fig)
			]),
			dcc.Tab(label='Cumulative Usage vs Capacity', children=[
				dcc.Graph(id="usage", figure=usage_fig)
			]),
			dcc.Tab(label='Precedence Graph', children=[
				dcc.Graph(id="precedence", figure=precedence_fig)
			])
		])
	])

	typer.echo("Starting Dash server at http://127.0.0.1:8050/")
	app.run(debug=False)

if __name__ == "__main__":
	app_typer()