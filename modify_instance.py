import os
import glob
import json
import typer

from rcpsp_sandbox.instances.io import parse_psplib
from rcpsp_sandbox.instances.problem_modifier import modify_instance

app = typer.Typer(help="Batch convert PSPLIB instances into flat JSON formats.")

@app.command()
def convert(
	input_dir: str = typer.Option("data/base_instances", help="Directory containing .sm files"),
	output_dir: str = typer.Option("data/jsons", help="Directory to save the flat JSONs")
):
	"""
	Modifies a standard PSPLIB .sm files and exports them as jsons.
	"""
	
	os.makedirs(output_dir, exist_ok=True)
	
	sm_files = glob.glob(os.path.join(input_dir, "*.sm"))
	
	if not sm_files:
		typer.echo(f"No .sm files in {input_dir}")
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
		modifier.assign_job_due_dates(choice="gradual", gradual_base=0, gradual_interval=(0, 0)) #TODO: investigate error in rcpsp_sandbox for the earliest option
		modified_instance = modifier.generate_modified_instance()
		
		#flatten predecessors
		preds = {j.id_job: [] for j in modified_instance.jobs}
		for p in modified_instance.precedences:
			preds[p.id_child].append(p.id_parent)
			
		#flatten requests
		req_list = []
		for j in modified_instance.jobs:
			for r, amount in j.resource_consumption.consumption_by_resource.items():
				if amount > 0:
					req_list.append({"job": j.id_job, "resource": r.key, "amount": amount})
					
		#flatten shifts
		shift_dict = {}
		for r in modified_instance.resources:
			r_shifts = []
			if r.availability and r.availability.periodical_intervals:
				for interval in r.availability.periodical_intervals:
					r_shifts.append([interval.start, interval.end, interval.capacity])
			shift_dict[r.key] = r_shifts
			
		#flatten orders
		orders_list = []
		for c in modified_instance.components:
			sink_id = c.id_root_job
			job_obj = modified_instance.jobs_by_id[sink_id]
			orders_list.append({
				"sink_job": sink_id,
				"due_date": job_obj.due_date if job_obj.due_date else 0,
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
			
		typer.echo(f"Saved to {json_filename}")

if __name__ == "__main__":
	app()