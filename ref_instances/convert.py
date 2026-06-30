import json
import random
from pathlib import Path
import typer

import problem_instance
from problem_instance import ProblemInstance, PrecedenceGraph
from instance_generator import InstanceGenerator

problem_instance.get_file = lambda filepath: str(filepath)

app = typer.Typer(help="Convert PSPLIB .sm files to augmented JSON formats.")

def generate_json_from_sm(sm_filepath: str, out_filepath: str, mean: int = -4, variance: int = 10, step: int = 0):
	pi = ProblemInstance(sm_filepath)
	
	generator = InstanceGenerator(pi) #add constraints
	generator._scale_up_times()
	
	if pi.precedence_graph is None:
		pi.precedence_graph = PrecedenceGraph(pi)
		
	if pi.precedence_graph.component_count == 1: #multiple customer orders
		generator._relax_precedence_relations()
		pi.component_order = None
		pi.precedence_graph = PrecedenceGraph(pi)
		
	generator.generate_due_dates(mean, variance, step)
	
	_weights = [random.randint(3, 6) for _ in range(pi.jobs)]
	pi.component_weights = [_weights[node] for node in pi.component_order]

	#json serialize
	json_data = {
		"metadata": {
			"project_count": pi.project_count,
			"jobs_count": pi.jobs,
			"horizon": pi.horizon
		},
		"resources": {
			"renewable": pi.renewable_resources,
			"availabilities": pi.resource_availabilities,
			"shift_modes": pi.resource_shift_modes
		},
		"jobs": [],
		"orders": []
	}

	for i in range(pi.jobs):
		req = pi.requests_and_durations[i]
		prec = pi.precedence_relations[i]
		
		job_data = {
			"id": i,
			"duration": req.duration,
			"resource_requests": req.renewable_requests,
			"successors": [s - 1 for s in prec.successors if (s - 1) < pi.jobs] #normalize the ids
		}
		
		json_data["jobs"].append(job_data)

	if pi.component_order:
		for idx, node in enumerate(pi.component_order):
			order_data = {
				"component_id": idx,
				"sink_node": node,
				"weight": pi.component_weights[idx],
				"due_date": pi.due_dates[node]
			}
			json_data["orders"].append(order_data)

	with open(out_filepath, "w") as f:
		json.dump(json_data, f, indent=4)
		
	print(f"Generated and saved: {out_filepath}")

@app.command()
def convert(
	input_path: Path = typer.Argument(..., help="Path to a single .sm file or a directory containing .sm files."),
	output_dir: Path = typer.Option(None, "--output-dir", "-o", help="Directory to save the JSON files. Defaults to the same directory as the input."),
	mean: int = typer.Option(-4, "--mean", "-m", help="Mean for random variable due date generation."),
	variance: int = typer.Option(10, "--variance", "-v", help="Variance for random variable due date generation."),
	step: int = typer.Option(0, "--step", "-s", help="Step for random variable due date generation.")
):
	"""
	Process PSPLIB .sm files and convert them into JSON structures augmented with real-world constraints.
	"""
	if not input_path.exists():
		typer.secho(f"Error: Path '{input_path}' does not exist.", fg=typer.colors.RED)
		raise typer.Exit(code=1)

	if input_path.is_file(): #files to process
		files_to_process = [input_path]
	elif input_path.is_dir():
		files_to_process = list(input_path.glob("*.sm")) + list(input_path.glob("*.sm.txt"))
		if not files_to_process:
			typer.secho(f"No .sm or .sm.txt files found in directory '{input_path}'.", fg=typer.colors.YELLOW)
			raise typer.Exit()
	else:
		typer.secho("Invalid input path.", fg=typer.colors.RED)
		raise typer.Exit(code=1)

	if output_dir:
		output_dir.mkdir(parents=True, exist_ok=True)

	success_count = 0
	error_count = 0

	for file_path in files_to_process:
		base_name = file_path.name.replace('.sm.txt', '').replace('.sm', '')
		out_filename = f"{base_name}.json"
		
		if output_dir:
			out_filepath = output_dir / out_filename
		else:
			out_filepath = file_path.parent / out_filename

		try:
			generate_json_from_sm(
				sm_filepath=str(file_path),
				out_filepath=str(out_filepath),
				mean=mean,
				variance=variance,
				step=step
			)
			success_count += 1
		except Exception as e:
			typer.secho(f"Error processing {file_path.name}: {e}", fg=typer.colors.RED)
			error_count += 1

	typer.secho(f"\nProcessing complete. Successfully generated {success_count} files. Errors: {error_count}.", fg=typer.colors.GREEN if error_count == 0 else typer.colors.YELLOW)

if __name__ == "__main__":
	app()