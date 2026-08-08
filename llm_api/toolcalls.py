import json
import os
import sys
import io
import jsonschema
from collections import defaultdict

sys.path.append(os.path.abspath(".."))
from solver import MRCPSP_solver
from llm_api.schema_validator import validate_instance

#caching
current_instance = {}
latest_schedule = {}
latest_obj_val = 0

def load_instance(filepath: str):
	global current_instance
	with open(filepath, "r") as f:
		current_instance = json.load(f)

def get_current_instance() -> dict:
	return current_instance

def query_instance_data(paths: list[str]) -> dict:
	global current_instance
	print(f"\n[TOOL CALLED] query_instance_data: {paths}")

	if not current_instance:
		return {"status": "error", "error": "No instance is currently loaded."}

	result = {}
	for path in paths:
		keys = path.split(".")
		ref = current_instance
		try:
			for k in keys:
				if isinstance(ref, list):
					ref = ref[int(k)]
				else:
					if k not in ref and str(k) in ref:
						k = str(k)
					ref = ref[k]
			result[path] = ref
		except (KeyError, IndexError, ValueError, TypeError) as e:
			result[path] = f"Error: Path not found ({str(e)})"

	return {"status": "success", "data": result}

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
	global current_instance, latest_schedule, latest_obj_val
	print(f"\n[TOOL CALLED] run_solver (time_limit={time_limit}s)")

	if not current_instance:
		return {"status": "error", "error": "No instance is currently loaded."}

	try:
		formatted_durations = {int(k): v for k, v in current_instance["durations"].items()}
		formatted_predecessors = {int(k): [int(p) for p in v] for k, v in current_instance.get("predecessors", {}).items()}

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

		old_stdout = sys.stdout
		sys.stdout = log_capture = io.StringIO()

		try:
			obj_val = solver.solve(time_limit=time_limit, log_output=True)
		finally:
			sys.stdout = old_stdout

		solver_log = log_capture.getvalue()
		schedule = solver.get_schedule()

		if obj_val is None or schedule is None:
			return {
				"status": "infeasible",
				"message": "No solution found.",
				"solver_log": solver_log
			}

		latest_schedule = {str(k): list(v) for k, v in schedule.items()}
		latest_obj_val = obj_val

		return {
			"status": "success",
			"weighted_tardiness": obj_val,
			"schedule": latest_schedule,
			"solver_log": solver_log
		}

	except Exception as e:
		return {"status": "error", "error": str(e)}

def visualize_schedule() -> dict:
	global current_instance, latest_schedule, latest_obj_val
	print("\n[TOOL CALLED] visualize_schedule")

	if not current_instance or not latest_schedule:
		return {"status": "error", "error": "No schedule available. Please run the solver first."}

	max_end = max((e for s, e in latest_schedule.values() if e is not None), default=0)
	resources = current_instance.get("resources", [])
	requests = {(req["job"], req["resource"]): req["amount"] for req in current_instance.get("requests", [])}
	shifts = current_instance.get("shifts", {})
	orders = current_instance.get("orders", [])
	orders_map = {str(o["sink_job"]): o for o in orders}

	gantt_data = {}
	for r in resources:
		placed_rects = []
		r_jobs = [j for j in current_instance["jobs"] if requests.get((j, r), 0) > 0 and str(j) in latest_schedule]
		r_jobs.sort(key=lambda j: (-requests.get((j, r), 0), latest_schedule[str(j)][0]))

		tasks = []
		for j in r_jobs:
			s, e = latest_schedule[str(j)]
			amount = requests[(j, r)]
			if s == e: continue

			y_base = 0
			while True:
				overlap = False
				for rs, re, ry_bot, ry_top in placed_rects:
					if max(s, rs) < min(e, re):
						if max(y_base, ry_bot) < min(y_base + amount, ry_top):
							overlap = True
							y_base = ry_top
							break
				if not overlap: break

			placed_rects.append((s, e, y_base, y_base + amount))
			is_sink = str(j) in orders_map
			tasks.append({
				"job": j, "start": s, "end": e, "amount": amount, "y_base": y_base,
				"is_sink": is_sink,
				"due_date": orders_map[str(j)]["due_date"] if is_sink else None
			})

		cap_intervals = []
		for start, end, c in shifts.get(r, []):
			if start <= max_end:
				cap_intervals.append({"start": start, "end": min(end, max_end), "cap": c})

		gantt_data[r] = {"tasks": tasks, "capacity": cap_intervals}

	usage_data = {}
	for r in resources:
		usage = [0] * (max_end + 1)
		for (j, res), amount in requests.items():
			if res == r and str(j) in latest_schedule:
				s, e = latest_schedule[str(j)]
				for t in range(s, min(e, max_end + 1)):
					usage[t] += amount

		cap = [0] * (max_end + 1)
		for start, end, c in shifts.get(r, []):
			for t in range(start, min(end, max_end + 1)):
				cap[t] = c

		usage_data[r] = {"usage": usage, "capacity": cap}

	predecessors = current_instance.get("predecessors", {})
	layers = {int(j): 0 for j in current_instance["jobs"]}

	for _ in range(len(current_instance["jobs"])):
		for j in current_instance["jobs"]:
			j_int = int(j)
			preds = predecessors.get(str(j), [])
			if preds:
				layers[j_int] = max([layers[int(p)] for p in preds if int(p) in layers], default=0) + 1

	layer_nodes = defaultdict(list)
	for j in current_instance["jobs"]:
		layer_nodes[layers[int(j)]].append(int(j))

	pos = {}
	x_spacing = 120
	y_spacing = 60
	for layer, nodes in layer_nodes.items():
		for idx, n in enumerate(nodes):
			pos[n] = {"x": layer * x_spacing + 50, "y": idx * y_spacing + 50}

	precedence_nodes = [
		{"id": int(j), "layer": layers[int(j)], "x": pos[int(j)]["x"], "y": pos[int(j)]["y"], "is_sink": str(j) in orders_map}
		for j in current_instance["jobs"]
	]

	precedence_edges = []
	for j_str, preds in predecessors.items():
		j_int = int(j_str)
		for p in preds:
			p_int = int(p)
			if p_int in pos and j_int in pos:
				precedence_edges.append({
					"from": p_int, "to": j_int,
					"x1": pos[p_int]["x"], "y1": pos[p_int]["y"],
					"x2": pos[j_int]["x"], "y2": pos[j_int]["y"]
				})

	max_x = max((n["x"] for n in precedence_nodes), default=0) + 100
	max_y = max((n["y"] for n in precedence_nodes), default=0) + 100

	return {
		"status": "success",
		"visualization_type": "full_dashboard",
		"weighted_tardiness": latest_obj_val,
		"max_time": max_end,
		"gantt": gantt_data,
		"usage": usage_data,
		"precedence": {"nodes": precedence_nodes, "edges": precedence_edges, "max_x": max_x, "max_y": max_y}
	}

openai_tools_schema = [
	{
		"type": "function",
		"function": {
			"name": "query_instance_data",
			"description": "Query specific parts of the loaded JSON instance using dot notation.",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {
					"paths": {
						"type": "array",
						"items": {
							"type": "string"
						},
						"description": "List of dot-separated paths to retrieve. Example: ['orders', 'durations.22', 'shifts.R1']"
					}
				},
				"required": ["paths"],
				"additionalProperties": False
			}
		}
	},
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
	},
	{
		"type": "function",
		"function": {
			"name": "visualize_schedule",
			"description": "Generate visualization data for the current solved schedule (Gantt chart timeline).",
			"strict": True,
			"parameters": {
				"type": "object",
				"properties": {},
				"required": [],
				"additionalProperties": False
			}
		}
	}
]
