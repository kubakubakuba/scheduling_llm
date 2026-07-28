import json
import os
import sys
import jsonschema

sys.path.append(os.path.abspath(".."))
from solver import MRCPSP_solver
from schema_validator import validate_instance

current_instance = {}

def load_instance(filepath: str):
	global current_instance
	with open(filepath, "r") as f:
		current_instance = json.load(f)

def get_current_instance() -> dict:
	return current_instance

def edit_json_in_place(path: str, new_value: float) -> dict:
	global current_instance
	print(f"\n[TOOL CALLED] edit_json_in_place: {path} -> {new_value}")

	keys = path.split(".")
	ref = current_instance

	try:
		for k in keys[:-1]:
			if isinstance(ref, list):
				ref = ref[int(k)]
			else:
				ref = ref[k]

		last_key = keys[-1]
		if isinstance(ref, list):
			ref[int(last_key)] = new_value
		else:
			if last_key not in ref and str(last_key) in ref:
				last_key = str(last_key)
			ref[last_key] = new_value

		validate_instance(current_instance)

		file_path = os.path.abspath("updated_instance.json")
		with open(file_path, "w") as out_f:
			json.dump(current_instance, out_f, indent=2)

		print(f"[TOOL SUCCESS] Edited {path} and saved.")
		return {"status": "success", "message": f"Updated {path} to {new_value}"}

	except (KeyError, IndexError, ValueError) as e:
		return {"status": "error", "error": f"Invalid path {path}: {str(e)}"}
	except jsonschema.ValidationError as e:
		return {"status": "schema_error", "error": e.message}

def propose_updated_instance(updated_instance: dict) -> dict:
	global current_instance
	print("\n[TOOL CALLED] propose_updated_instance")

	try:
		validate_instance(updated_instance)
		current_instance = updated_instance

		file_path = os.path.abspath("updated_instance.json")
		with open(file_path, "w") as out_f:
			json.dump(current_instance, out_f, indent=2)

		return {"status": "success", "message": "Instance updated."}

	except jsonschema.ValidationError as e:
		return {
			"status": "schema_error",
			"error": e.message,
			"instruction": "Fix the JSON structure according to the error message.",
		}

def run_solver(time_limit: int = 30) -> dict:
	global current_instance
	print(f"\n[TOOL CALLED] run_solver (time_limit={time_limit}s)")

	try:
		formatted_durations = {int(k): v for k, v in current_instance["durations"].items()}
		formatted_predecessors = {int(k): v for k, v in current_instance["predecessors"].items()}
		
		formatted_requests = {}
		for req in current_instance["requests"]:
			formatted_requests[(req["job"], req["resource"])] = req["amount"]

		solver = MRCPSP_solver(
			jobs=current_instance["jobs"],
			durations=formatted_durations,
			predecessors=formatted_predecessors,
			resources=current_instance["resources"],
			requests=formatted_requests,
			shifts=current_instance["shifts"],
			orders=current_instance["orders"],
		)

		solver.init_model()
		obj_val = solver.solve(time_limit=time_limit, log_output=False)
		schedule = solver.get_schedule()

		if obj_val is None or schedule is None:
			return {"status": "infeasible", "message": "No solution found."}

		return {
			"status": "success",
			"weighted_tardiness": obj_val,
			"schedule": {str(k): list(v) for k, v in schedule.items()},
		}

	except Exception as e:
		return {"status": "error", "error": str(e)}

#tool schema for openai
openai_tools_schema = [
	{
		"type": "function",
		"function": {
			"name": "edit_json_in_place",
			"description": "Edit a specific scalar value. Use ONLY dot notation for arrays (e.g., 'orders.0.due_date'). DO NOT use brackets like 'orders[0]'.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"path": {
						"type": "string",
						"description": "Dot-separated path. Example: 'durations.22' or 'orders.5.due_date'. No brackets allowed."
					},
					"new_value": {
						"type": "number",
						"description": "The new numerical value to set."
					}
				},
				"required": ["path", "new_value"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "propose_updated_instance",
			"description": "Propose a completely updated Modified-RCPSP problem instance.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"updated_instance": {
						"type": "object",
						"description": "The full JSON object representing the modified problem."
					}
				},
				"required": ["updated_instance"],
				"additionalProperties": False
			}
		}
	},
	{
		"type": "function",
		"function": {
			"name": "run_solver",
			"description": "Run the CP Optimizer solver on the current problem instance state.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"time_limit": {
						"type": "integer",
						"description": "Maximum solver run time in seconds."
					}
				},
				"required": ["time_limit"],
				"additionalProperties": False
			}
		}
	}
]