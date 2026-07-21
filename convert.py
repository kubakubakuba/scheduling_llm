import os
import glob
import json
import typer

from rcpsp_sandbox.instances.io import parse_psplib
from rcpsp_sandbox.instances.problem_modifier import modify_instance

app = typer.Typer(help="Batch convert PSPLIB instances into flat JSON formats for custom solvers.")

@app.command()
def convert(
	input_dir: str = typer.Option("data/base_instances", help="Directory containing .sm files"),
	output_dir: str = typer.Option("data/jsons", help="Directory to save the flat JSONs"),
	tightness: float = typer.Option(1.3, help="Multiplier for the CPM early finish time to set realistic deadlines")
):
	"""
	Reads standard RCPSP .sm files, applies modifications (shifts, deadlines, orders), 
	and exports them as flat JSON files tailored for the custom CP solver.
	"""

	os.makedirs(output_dir, exist_ok=True)
	
	sm_files = glob.glob(os.path.join(input_dir, "*.sm"))
	
	if not sm_files:
		typer.echo(f"Error: No .sm files found in {input_dir}")
		raise typer.Exit()

	for filepath in sm_files:
		filename = os.path.basename(filepath)
		json_filename = filename.replace(".sm", ".json")
		output_path = os.path.join(output_dir, json_filename)
		
		typer.echo(f"Processing {filename}")
		
		base_instance = parse_psplib(filepath)
		
		modifier = modify_instance(base_instance)
		
		shifts_config = {r.key: [(6, 22)] for r in base_instance.resources}
		modifier.assign_resource_availabilities(availabilities=shifts_config)
		
		modifier.split_job_components(split="gradual", gradual_level=2)
		
		#true earliest finish times (critical path)
		durations = {j.id_job: j.duration for j in modifier.jobs}
		adj = {j.id_job: [] for j in modifier.jobs}
		in_degree = {j.id_job: 0 for j in modifier.jobs}
		
		for p in modifier.precedences:
			adj[p.id_parent].append(p.id_child)
			in_degree[p.id_child] += 1
			
		#init Q
		queue = [j for j, deg in in_degree.items() if deg == 0]
		earliest_finish = {j: durations[j] for j in queue}
		
		#fw pass
		while queue:
			curr = queue.pop(0)
			for child in adj[curr]:
				new_ef = earliest_finish[curr] + durations[child]
				
				if child not in earliest_finish or new_ef > earliest_finish[child]:
					earliest_finish[child] = new_ef
					
				in_degree[child] -= 1
				
				if in_degree[child] == 0:
					queue.append(child)
					
		deadlines = {j: int(ef * tightness) for j, ef in earliest_finish.items()}
		
		#assign manually created
		modifier.assign_job_due_dates(due_dates=deadlines)
		
		modified_instance = modifier.generate_modified_instance()
		
		#flatten predecessors
		preds = {j.id_job: [] for j in modified_instance.jobs}
		for p in modified_instance.precedences:
			preds[p.id_parent].append(p.id_child)
			
		#flatten requests
		req_list = []
		for j in modified_instance.jobs:
			for r, amount in j.resource_consumption.consumption_by_resource.items():
				if amount > 0:
					req_list.append({"job": j.id_job, "resource": r.key, "amount": amount})
					
		#shifts
		shift_dict = {}
		for r in modified_instance.resources:
			r_shifts = []
			if r.availability and r.availability.periodical_intervals:
				for interval in r.availability.periodical_intervals:
					r_shifts.append([interval.start, interval.end, interval.capacity])
			shift_dict[r.key] = r_shifts
			
		#orders
		orders_list = []
		for c in modified_instance.components:
			sink_id = c.id_root_job
			
			orders_list.append({
				"sink_job": sink_id,
				"due_date": deadlines.get(sink_id, 0),
				"weight": c.weight
			})
		
		json_data = {
			"instance_name": filename,
			"jobs": [j.id_job for j in modified_instance.jobs],
			"durations": {j.id_job: j.duration for j in modified_instance.jobs},
			"predecessors": preds,
			"resources": [r.key for r in modified_instance.resources],
			"requests": req_list,
			"shifts": shift_dict,
			"orders": orders_list
		}
		
		with open(output_path, 'w', encoding='utf-8') as f:
			json.dump(json_data, f, indent=2)
			
		typer.echo(f"saved to {json_filename}")

if __name__ == "__main__":
	app()