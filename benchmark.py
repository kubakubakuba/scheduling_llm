import os
import json
import glob
import typer

from solver import MRCPSP_solver as Solver

app = typer.Typer(help="Benchmark script for evaluating the Modified RCPSP solver on JSON instances.")

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

@app.command()
def run(
	path: str = typer.Argument(..., help="Path to a single JSON file or a directory containing JSON files"),
	time_limit: int = typer.Option(60, help="Time limit for the CP solver in seconds per instance"),
	verbose: bool = typer.Option(False, help="Print detailed CP Optimizer logs")
):
	"""
	Runs the Solver on the specified JSON instance(s).
	"""
	
	if os.path.isfile(path):
		files = [path]
	
	elif os.path.isdir(path):
		files = glob.glob(os.path.join(path, "*.json"))
		files.sort()

		if not files:
			typer.echo(f"No JSON files found in: {path}")
			raise typer.Exit()
	
	else:
		typer.echo(f"Invalid path: {path}")
		raise typer.Exit()
	
	typer.echo(f"Found {len(files)} instance(s) to solve.\n")
	
	results = {}
	
	for f in files:
		filename = os.path.basename(f)
		typer.echo(f"Solving {filename}...")
		
		try:
			instance_data = load_instance(f)
			
			solver = Solver(**instance_data)
			solver.init_model()
			obj_val = solver.solve(time_limit=time_limit, log_output=verbose)
			
			if obj_val is not None:
				results[filename] = obj_val
				typer.echo(f"---> Optimal Tardiness: {obj_val} <---")
			
			else:
				results[filename] = "No Solution"
				typer.echo(f"---> Failed to find a solution within {time_limit}s. <---")
				
		except Exception as e:
			typer.echo(f"---> Error: {e} <---")
			results[filename] = f"Error: {e}"

	typer.echo("\n" + "="*30)
	typer.echo("SUMMARY")
	typer.echo("="*30)
	for filename, res in results.items():
		typer.echo(f"{filename:<25} | {res}")

if __name__ == "__main__":
	app()