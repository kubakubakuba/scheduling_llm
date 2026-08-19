import jsonschema

import llm_api.schema as schema


def _error(path, code, message):
	return {"path": path, "code": code, "message": message}


def _format_path(path):
	parts = [str(part) for part in path]
	return ".".join(parts) if parts else "$"


def validate_json_schema(instance_data):
	"""Return every JSON-Schema error without raising on the first one."""
	validator = jsonschema.Draft202012Validator(schema.MRCPSP_SCHEMA)
	errors = []

	for error in sorted(
		validator.iter_errors(instance_data),
		key=lambda item: tuple(str(part) for part in item.absolute_path),
	):
		code = {
			"additionalProperties": "unknown_field",
			"required": "missing_required_field",
			"type": "wrong_type",
			"minimum": "below_minimum",
			"uniqueItems": "duplicate_item",
		}.get(error.validator, "schema_validation")
		errors.append(_error(
			_format_path(error.absolute_path), code, error.message
		))

	return errors


def build_successors(jobs, predecessors):
	successors = {int(job): set() for job in jobs}
	for after, before_list in predecessors.items():
		after = int(after)
		for before in before_list:
			before = int(before)
			successors.setdefault(before, set()).add(after)
	return successors


def reachable(successors, start, target):
	stack = [start]
	visited = set()
	while stack:
		current = stack.pop()
		if current == target:
			return True
		if current in visited:
			continue
		visited.add(current)
		stack.extend(successors.get(current, []))
	return False


def would_create_cycle(jobs, predecessors, before, after):
	"""Return whether adding the arc before -> after would close a cycle."""
	return reachable(build_successors(jobs, predecessors), after, before)


def find_cycle(successors):
	"""Return one concrete cycle, or None if the graph is acyclic."""
	state = {job: 0 for job in successors}  # 0=unvisited, 1=active, 2=done
	stack = []
	stack_index = {}

	def visit(job):
		state[job] = 1
		stack_index[job] = len(stack)
		stack.append(job)
		for successor in successors.get(job, ()):
			if state[successor] == 0:
				cycle = visit(successor)
				if cycle:
					return cycle
			elif state[successor] == 1:
				return stack[stack_index[successor]:] + [successor]
		stack.pop()
		stack_index.pop(job, None)
		state[job] = 2
		return None

	for job in sorted(successors):
		if state[job] == 0:
			cycle = visit(job)
			if cycle:
				return cycle
	return None


def validate_precedence_graph(jobs, predecessors):
	"""Return precedence errors instead of raising the first error."""
	errors = []
	job_set = {int(job) for job in jobs}

	for after_key, predecessor_list in predecessors.items():
		after = int(after_key)
		if after not in job_set:
			continue  # reported by the exact-key check below
		if len(predecessor_list) != len(set(predecessor_list)):
			errors.append(_error(
				f"predecessors.{after}", "duplicate_predecessor",
				f"Job {after} contains duplicate predecessors."
			))
		for before in predecessor_list:
			if before not in job_set:
				errors.append(_error(
					f"predecessors.{after}", "unknown_job",
					f"Job {after} refers to unknown predecessor {before}."
				))
			elif before == after:
				errors.append(_error(
					f"predecessors.{after}", "self_precedence",
					f"Job {after} cannot be its own predecessor."
				))

	valid_predecessors = {
		int(after): [int(before) for before in values if int(before) in job_set]
		for after, values in predecessors.items()
		if int(after) in job_set
	}
	cycle = find_cycle(build_successors(job_set, valid_predecessors))
	if cycle:
		errors.append(_error(
			"predecessors", "precedence_cycle",
			"Precedence graph contains cycle: "
			+ " -> ".join(map(str, cycle)) + "."
		))
	return errors


def validate_semantic_references(instance_data):
	"""Return all semantic errors for a structurally valid instance."""
	errors = []
	jobs = instance_data["jobs"]
	job_set = set(jobs)

	if len(jobs) != len(job_set):
		errors.append(_error(
			"jobs", "duplicate_job", "The jobs list contains duplicate job IDs."
		))

	duration_jobs = {int(job_id) for job_id in instance_data["durations"]}
	if job_set - duration_jobs:
		errors.append(_error(
			"durations", "missing_job",
			f"Missing durations for jobs: {sorted(job_set - duration_jobs)}."
		))
	if duration_jobs - job_set:
		errors.append(_error(
			"durations", "unknown_job",
			f"Durations contain unknown jobs: {sorted(duration_jobs - job_set)}."
		))

	predecessor_jobs = {int(job_id) for job_id in instance_data["predecessors"]}
	if job_set - predecessor_jobs:
		errors.append(_error(
			"predecessors", "missing_job",
			"Missing predecessor entries for jobs: "
			+ f"{sorted(job_set - predecessor_jobs)}."
		))
	if predecessor_jobs - job_set:
		errors.append(_error(
			"predecessors", "unknown_job",
			"Predecessors contain unknown jobs: "
			+ f"{sorted(predecessor_jobs - job_set)}."
		))
	errors.extend(validate_precedence_graph(jobs, instance_data["predecessors"]))

	resources = set(instance_data["resources"])
	shift_resources = set(instance_data["shifts"])
	if resources - shift_resources:
		errors.append(_error(
			"shifts", "missing_resource",
			"Missing shift calendars for resources: "
			+ f"{sorted(resources - shift_resources)}."
		))
	if shift_resources - resources:
		errors.append(_error(
			"shifts", "unknown_resource",
			"Shift calendars contain unknown resources: "
			+ f"{sorted(shift_resources - resources)}."
		))

	request_pairs = set()
	for index, request in enumerate(instance_data["requests"]):
		job = request["job"]
		resource = request["resource"]
		pair = (job, resource)
		if job not in job_set:
			errors.append(_error(
				f"requests.{index}.job", "unknown_job",
				f"Request refers to unknown job {job}."
			))
		if resource not in resources:
			errors.append(_error(
				f"requests.{index}.resource", "unknown_resource",
				f"Request refers to unknown resource {resource}."
			))
		if pair in request_pairs:
			errors.append(_error(
				f"requests.{index}", "duplicate_request",
				f"Duplicate request for job {job} and resource {resource}."
			))
		request_pairs.add(pair)

	for resource, intervals in instance_data["shifts"].items():
		valid_intervals = []
		for index, interval in enumerate(intervals):
			start, end, capacity = interval
			if start >= end:
				errors.append(_error(
					f"shifts.{resource}.{index}", "invalid_interval",
					"Interval must satisfy start < end."
				))
			else:
				valid_intervals.append((start, end, index))
			if capacity < 0:
				errors.append(_error(
					f"shifts.{resource}.{index}.2", "negative_capacity",
					"Capacity must be non-negative."
				))

		valid_intervals.sort()
		for previous, current in zip(valid_intervals, valid_intervals[1:]):
			if current[0] < previous[1]:
				errors.append(_error(
					f"shifts.{resource}", "overlapping_intervals",
					f"Intervals {previous[2]} and {current[2]} overlap."
				))

	orders = instance_data["orders"]
	order_sinks = set()
	for index, order in enumerate(orders):
		sink = order["sink_job"]
		if sink not in job_set:
			errors.append(_error(
				f"orders.{index}.sink_job", "unknown_job",
				f"Order refers to unknown sink job {sink}."
			))
		if sink in order_sinks:
			errors.append(_error(
				f"orders.{index}.sink_job", "duplicate_order_sink",
				f"Order sink job {sink} appears more than once."
			))
		order_sinks.add(sink)

	# The enforceable interpretation of "intended completion job" here is
	# that an order sink is terminal: no job may depend on it.
	successors = build_successors(
		job_set,
		{
			int(after): [int(before) for before in values]
			for after, values in instance_data["predecessors"].items()
		}
	)
	for index, order in enumerate(orders):
		sink = order["sink_job"]
		if sink in job_set and successors.get(sink):
			errors.append(_error(
				f"orders.{index}.sink_job", "non_terminal_sink",
				f"Order sink job {sink} has successors and is not terminal."
			))

	return errors


def validate_instance(instance_data):
	"""Return [] for a valid instance, otherwise structured errors."""
	if not isinstance(instance_data, dict):
		return [_error("$", "wrong_type", "Instance must be a JSON object.")]

	structural_errors = validate_json_schema(instance_data)
	if structural_errors:
		# Avoid cascading KeyError/TypeError failures in semantic validation.
		# iter_errors() has already collected every structural error.
		return structural_errors

	return validate_semantic_references(instance_data)
