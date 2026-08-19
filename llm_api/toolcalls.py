import json
import os
import sys
import io
import jsonschema
from collections import defaultdict
import copy

sys.path.append(os.path.abspath(".."))
from solver import MRCPSP_solver

from llm_api.schema_validator import (
	validate_instance,
	would_create_cycle
)

from llm_api.util import (
	InvalidPathError,
	_get_path,
	_set_path,
	_atomic_write_json,
	_commit_candidate as _write_commit_candidate
)

#caching
current_instance = {}
current_revision = 0

latest_schedule = {}
latest_obj_val = None

latest_solver = None
latest_solver_result = None
latest_solved_revision = None

def _invalidate_solver_cache():
	global latest_schedule
	global latest_obj_val
	global latest_solver
	global latest_solver_result
	global latest_solved_revision

	latest_schedule = {}
	latest_obj_val = None
	latest_solver = None
	latest_solver_result = None
	latest_solved_revision = None


def _validation_failure(errors):
	return {
		"status": "rejected",
		"error_code": "invalid_instance",
		"message": "The candidate instance failed validation.",
		"validation_errors": errors,
		"instance_modified": False,
	}


def _commit_candidate(candidate: dict, message: str) -> dict:
	"""Validate and commit one candidate instance transactionally."""
	global current_instance
	global current_revision

	errors = validate_instance(candidate)

	if errors:
		return _validation_failure(errors)

	result = _write_commit_candidate(candidate, message)

	#do not change live instance if failed
	if result.get("status") not in {"success", "committed"}:
		return result

	current_instance = candidate
	current_revision += 1

	_invalidate_solver_cache()

	result["revision"] = current_revision
	result["instance_modified"] = True

	return result


def load_instance(filepath: str) -> dict:
	global current_instance
	global current_revision

	with open(filepath, "r", encoding="utf-8") as file:
		candidate = json.load(file)

	errors = validate_instance(candidate)

	if errors:
		return _validation_failure(errors)

	current_instance = candidate
	current_revision += 1
	_invalidate_solver_cache()

	return {
		"status": "success",
		"message": "Instance loaded and validated.",
		"revision": current_revision,
		"instance_modified": False,
	}

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

def edit_json_in_place(path: str, new_value) -> dict:
	global current_instance

	if not current_instance:
		return {
			"status": "error",
			"message": "No instance is currently loaded."
		}

	candidate = copy.deepcopy(current_instance)

	try:
		old_value = _get_path(candidate, path)

		if isinstance(old_value, (dict, list)):
			return {
				"status": "rejected",
				"error_code": "not_scalar",
				"message": (
					f"The path '{path}' refers to an object or list. "
					"Use a dedicated structural tool instead."
				),
				"instance_modified": False,
			}

		_set_path(candidate, path, new_value)

		result = _commit_candidate(
			candidate,
			f"Updated {path} from {old_value} to {new_value}."
		)

		result["path"] = path
		result["old_value"] = old_value
		result["new_value"] = new_value

		return result

	except InvalidPathError as exc:
		return {
			"status": "rejected",
			"error_code": "invalid_path",
			"message": str(exc),
			"instance_modified": False,
		}

def propose_updated_instance(updated_instance: dict) -> dict:
	if not isinstance(updated_instance, dict):
		return {
			"status": "rejected",
			"error_code": "invalid_type",
			"message": "updated_instance must be a JSON object.",
			"instance_modified": False,
		}

	candidate = copy.deepcopy(updated_instance)

	result = _commit_candidate(
		candidate,
		"The proposed instance was validated and committed."
	)

	if result["status"] == "rejected":
		result["instruction"] = (
			"The candidate was not applied. Correct the reported "
			"validation errors and propose it again."
		)

	return result

def build_solver(instance_data: dict) -> MRCPSP_solver:
	formatted_durations = {
		int(job): duration
		for job, duration in instance_data["durations"].items()
	}

	formatted_predecessors = {
		int(job): [int(predecessor) for predecessor in predecessors]
		for job, predecessors in instance_data["predecessors"].items()
	}

	formatted_requests = {
		(request["job"], request["resource"]): request["amount"]
		for request in instance_data["requests"]
	}

	solver = MRCPSP_solver(
		jobs=instance_data["jobs"],
		durations=formatted_durations,
		predecessors=formatted_predecessors,
		resources=instance_data["resources"],
		requests=formatted_requests,
		shifts=instance_data["shifts"],
		orders=instance_data["orders"],
	)

	solver.init_model()
	return solver

def run_solver(time_limit: int = 30) -> dict:
	global current_instance
	global current_revision
	global latest_schedule
	global latest_obj_val
	global latest_solver
	global latest_solver_result
	global latest_solved_revision

	print(f"\n[TOOL CALLED] run_solver (time_limit={time_limit}s)")

	if not current_instance:
		return {
			"status": "error",
			"error_code": "no_instance",
			"message": "No instance is currently loaded.",
			"has_solution": False,
			"conflict_refiner_available": False,
		}

	#validate before solving
	validation_errors = validate_instance(current_instance)

	if validation_errors:
		latest_schedule = {}
		latest_obj_val = None
		latest_solver = None
		latest_solver_result = None
		latest_solved_revision = None

		return {
			"status": "invalid_instance",
			"error_code": "validation_failed",
			"message": (
				"The current instance is invalid; "
				"solving was not attempted."
			),
			"validation_errors": validation_errors,
			"has_solution": False,
			"schedule": None,
			"weighted_tardiness": None,
			"conflict_refiner_available": False,
		}

	try:
		solver = build_solver(current_instance)

		result = solver.solve(
			time_limit=time_limit,
			log_output=True,
		)

		#store model definition for conflict refiner
		latest_solver = solver
		latest_solver_result = result
		latest_solved_revision = current_revision

		status = result["status"]
		has_solution = result.get("has_solution", False)

		if has_solution:
			raw_schedule = result.get("schedule")

			if raw_schedule is None:
				raise RuntimeError(
					"The solver reported a solution but returned no schedule."
				)

			latest_schedule = {
				str(job): list(times)
				for job, times in raw_schedule.items()
			}

			latest_obj_val = result.get("objective")

			# Keep the names currently expected by your visualisation code.
			result["schedule"] = latest_schedule
			result["weighted_tardiness"] = latest_obj_val

		else:
			latest_schedule = {}
			latest_obj_val = None

			result["schedule"] = None
			result["weighted_tardiness"] = None

		messages = {
			"optimal": (
				"An optimal schedule was found."
			),
			"feasible": (
				"A feasible schedule was found, but optimality "
				"was not proved within the search limit."
			),
			"infeasible": (
				"CP Optimizer proved that the instance is infeasible."
			),
			"no_solution_limit": (
				"No feasible solution was found before the solver "
				"reached its search limit. Infeasibility was not proved."
			),
			"unknown": (
				"The solver stopped without finding a solution or "
				"proving infeasibility."
			),
			"aborted": (
				"The solver search was aborted."
			),
			"solver_error": (
				"CP Optimizer reported a solver failure."
			),
		}

		result["message"] = messages.get(
			status,
			"The solver returned an unrecognised status.",
		)

		# Refinement is allowed only for a proven infeasible result belonging
		# to the current instance revision.
		result["conflict_refiner_available"] = (
			status == "infeasible"
			and latest_solved_revision == current_revision
		)

		return result

	except Exception as exc:
		# Do not leave a previous solver result available after a failed run.
		latest_schedule = {}
		latest_obj_val = None
		latest_solver = None
		latest_solver_result = None
		latest_solved_revision = None

		return {
			"status": "solver_error",
			"error_code": "solver_exception",
			"message": "An error occurred while running CP Optimizer.",
			"error": str(exc),
			"error_type": type(exc).__name__,
			"has_solution": False,
			"schedule": None,
			"weighted_tardiness": None,
			"conflict_refiner_available": False,
		}

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
	max_due_date = max((o.get("due_date", 0) for o in orders), default=0)
	chart_max = max(max_end, max_due_date, 1)

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
			order = orders_map.get(str(j))
			is_sink = order is not None
			due_date = order["due_date"] if order else None
			weight = order["weight"] if order else None
			tardiness = max(0, e - due_date) if order else None
			weighted_contribution = weight * tardiness if order else None
			tasks.append({
				"job": j, "start": s, "end": e, "amount": amount, "y_base": y_base,
				"is_sink": is_sink,
				"due_date": due_date,
				"weight": weight,
				"tardiness": tardiness,
				"weighted_contribution": weighted_contribution
			})

		cap_intervals = []
		for start, end, c in shifts.get(r, []):
			if start <= chart_max:
				cap_intervals.append({"start": start, "end": min(end, chart_max), "cap": c})

		gantt_data[r] = {"tasks": tasks, "capacity": cap_intervals}

	usage_data = {}
	for r in resources:
		usage = [0] * (chart_max + 1)
		for (j, res), amount in requests.items():
			if res == r and str(j) in latest_schedule:
				s, e = latest_schedule[str(j)]
				for t in range(s, min(e, chart_max + 1)):
					usage[t] += amount

		cap = [0] * (chart_max + 1)
		for start, end, c in shifts.get(r, []):
			for t in range(start, min(end, chart_max + 1)):
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
		"max_time": chart_max,
		"schedule_end": max_end,
		"gantt": gantt_data,
		"usage": usage_data,
		"precedence": {"nodes": precedence_nodes, "edges": precedence_edges, "max_x": max_x, "max_y": max_y}
	}

def add_precedence_constraint(before: int, after: int) -> dict:
	if before not in current_instance["jobs"]:
		return {
			"status": "rejected",
			"error_code": "unknown_job",
			"message": f"Unknown job {before}.",
			"instance_modified": False,
		}

	if after not in current_instance["jobs"]:
		return {
			"status": "rejected",
			"error_code": "unknown_job",
			"message": f"Unknown job {after}.",
			"instance_modified": False,
		}

	candidate = copy.deepcopy(current_instance)
	predecessor_map = candidate["predecessors"]

	after_key = str(after)
	predecessor_list = predecessor_map[after_key]

	if before in predecessor_list:
		return {
			"status": "rejected",
			"error_code": "duplicate_precedence",
			"message": f"The precedence {before} → {after} already exists.",
			"instance_modified": False,
		}

	normalised_predecessors = {
		int(job): [int(p) for p in values]
		for job, values in predecessor_map.items()
	}

	if would_create_cycle(
		candidate["jobs"],
		normalised_predecessors,
		before=before,
		after=after
	):
		return {
			"status": "rejected",
			"error_code": "precedence_cycle",
			"message": (
				f"Adding {before} → {after} would create "
				"a circular dependency."
			),
			"instance_modified": False,
		}

	predecessor_list.append(before)

	return _commit_candidate(
		candidate,
		f"Added precedence constraint {before} → {after}."
	)

def set_order_due_date(sink_job: int, due_date: int) -> dict:
	candidate = copy.deepcopy(current_instance)

	matching = [
		(index, order)
		for index, order in enumerate(candidate["orders"])
		if order["sink_job"] == sink_job
	]

	if len(matching) != 1:
		return {
			"status": "rejected",
			"error_code": "unknown_or_duplicate_order",
			"message": (
				f"Expected exactly one order with sink job {sink_job}."
			),
			"instance_modified": False,
		}

	index, order = matching[0]
	old_due_date = order["due_date"]
	candidate["orders"][index]["due_date"] = due_date

	result = _commit_candidate(
		candidate,
		(
			f"Changed due date of order {sink_job} "
			f"from {old_due_date} to {due_date}."
		)
	)

	result.update({
		"sink_job": sink_job,
		"old_due_date": old_due_date,
		"new_due_date": due_date,
	})

	return result

def set_job_duration(job: int, duration: int) -> dict:
	if job not in current_instance["jobs"]:
		return {
			"status": "rejected",
			"error_code": "unknown_job",
			"message": f"Unknown job {job}.",
			"instance_modified": False,
		}

	candidate = copy.deepcopy(current_instance)
	key = str(job)

	old_duration = candidate["durations"][key]
	candidate["durations"][key] = duration

	result = _commit_candidate(
		candidate,
		(
			f"Changed duration of job {job} "
			f"from {old_duration} to {duration}."
		)
	)

	result.update({
		"job": job,
		"old_duration": old_duration,
		"new_duration": duration,
	})

	return result

def set_resource_capacity(
	resource: str,
	start: int,
	end: int,
	capacity: int
) -> dict:
	if resource not in current_instance["shifts"]:
		return {
			"status": "rejected",
			"error_code": "unknown_resource",
			"message": f"Unknown resource {resource}.",
			"instance_modified": False,
		}

	candidate = copy.deepcopy(current_instance)
	intervals = candidate["shifts"][resource]

	matches = [
		index
		for index, interval in enumerate(intervals)
		if interval[0] == start and interval[1] == end
	]

	if len(matches) != 1:
		return {
			"status": "rejected",
			"error_code": "interval_not_found",
			"message": (
				f"No unique interval [{start}, {end}) exists "
				f"for resource {resource}."
			),
			"instance_modified": False,
		}

	index = matches[0]
	old_capacity = intervals[index][2]
	intervals[index][2] = capacity

	result = _commit_candidate(
		candidate,
		(
			f"Changed capacity of {resource} during "
			f"[{start}, {end}) from {old_capacity} to {capacity}."
		)
	)

	result.update({
		"resource": resource,
		"start": start,
		"end": end,
		"old_capacity": old_capacity,
		"new_capacity": capacity,
	})

	return result

def remove_precedence_constraint(before: int, after: int) -> dict:
	candidate = copy.deepcopy(current_instance)
	after_key = str(after)

	if before not in candidate["predecessors"].get(after_key, []):
		return {
			"status": "rejected",
			"error_code": "precedence_not_found",
			"message": f"The precedence {before} → {after} does not exist.",
			"instance_modified": False,
		}

	candidate["predecessors"][after_key].remove(before)

	return _commit_candidate(
		candidate,
		f"Removed precedence constraint {before} → {after}."
	)
