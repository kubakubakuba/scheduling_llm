import math

from docplex.cp.model import (
	CpoModel,
	CpoStepFunction,
	INTERVAL_MAX
)

from docplex.cp.solution import (
	SOLVE_STATUS_OPTIMAL,
	SOLVE_STATUS_FEASIBLE,
	SOLVE_STATUS_INFEASIBLE,
	SOLVE_STATUS_JOB_ABORTED,
	SOLVE_STATUS_JOB_FAILED,
	STOP_CAUSE_LIMIT,
)

def _json_number(value):
	if value is None:
		return None

	if isinstance(value, float) and not math.isfinite(value):
		return None

	return value

class MRCPSP_solver:
	def __init__(self, jobs, durations, predecessors, resources, requests, shifts, orders):
		self.jobs = jobs
		self.dur = durations
		self.pred = predecessors
		self.res = resources
		self.req = requests
		self.shifts = shifts
		self.orders = orders

		self.m = None
		self.job_vars = {}
		self.sol = None
		self.constraint_metadata = {}

	def init_model(self):
		self.m = CpoModel(name="RCPSP")
		self.job_vars = {}

		#decision vars
		for j in self.jobs:
			self.job_vars[j] = self.m.interval_var(size=self.dur[j], name=f"Job_{j}")

		#precedences
		for j in self.jobs:
			for i in self.pred.get(j, []):
				self.m.add(self.m.end_before_start(self.job_vars[i], self.job_vars[j]))

		#resource capacity calendar
		for k in self.res:
			usage = 0

			#1 for off-hour (unavailable)
			avail_step = CpoStepFunction()

			#mark shift with 1 as available
			for start, end, cap in self.shifts.get(k, []):
				if cap > 0:
					avail_step.set_value(start, end, 1)

			for j in self.jobs:
				req_amount = self.req.get((j, k), 0)

				if req_amount > 0:
					usage += self.m.pulse(self.job_vars[j], req_amount)
					
					#forbid overlapping
					self.m.add(self.m.forbid_extent(self.job_vars[j], avail_step))

			#constrain capacity
			for start, end, cap in self.shifts.get(k, []):
				if cap > 0:
					self.m.add(self.m.always_in(usage, start, end, 0, cap))

		#objective
		tardiness = 0
		for o in self.orders:
			sink = self.job_vars[o['sink_job']]
			due_date = o['due_date']
			weight = o['weight']

			T = self.m.max(0, self.m.end_of(sink) - due_date)
			tardiness += weight * T

		self.m.add(self.m.minimize(tardiness))


	def solve(self, time_limit=30, log_output=True):
		self.sol = self.m.solve(
			TimeLimit=time_limit,
			LogVerbosity="Normal" if log_output else "Quiet",
		)

		result = self.sol
		solver_status = result.get_solve_status()
		search_status = result.get_search_status()
		stop_cause = result.get_stop_cause()

		if solver_status == SOLVE_STATUS_OPTIMAL:
			status = "optimal"

		elif solver_status == SOLVE_STATUS_FEASIBLE:
			status = "feasible"

		elif solver_status == SOLVE_STATUS_INFEASIBLE:
			status = "infeasible"

		elif solver_status == SOLVE_STATUS_JOB_ABORTED:
			status = "aborted"

		elif solver_status == SOLVE_STATUS_JOB_FAILED:
			status = "solver_error"

		elif stop_cause == STOP_CAUSE_LIMIT:
			status = "no_solution_limit"

		else:
			status = "unknown"

		response = {
			"status": status,
			"solver_status": solver_status,
			"search_status": search_status,
			"stop_cause": stop_cause,
			"has_solution": result.is_solution(),
			"is_optimal": result.is_solution_optimal(),
			"objective": _json_number(result.get_objective_value()),
			"best_bound": _json_number(result.get_objective_bound()),
			"relative_gap": _json_number(result.get_objective_gap()),
			"solve_time": _json_number(result.get_solve_time()),
			"solver_log": result.get_solver_log() or "",
		}

		if result.is_solution():
			response["schedule"] = self.get_schedule()
		else:
			response["schedule"] = None

		return response

	def print_solution(self):
		if not self.sol or not self.sol.is_solution():
			print("No solution found.")
			return
			
		for j in self.jobs:
			var_sol = self.sol.get_var_solution(self.job_vars[j])
			if var_sol:
				print(f"Job {j}: [{var_sol.get_start()}, {var_sol.get_end()}]")

	def get_schedule(self):
		if self.sol is None or not self.sol.is_solution():
			return None

		schedule = {}

		for job, variable in self.job_vars.items():
			variable_solution = self.sol.get_var_solution(variable)

			if variable_solution is None or not variable_solution.is_present():
				continue

			schedule[job] = (
				variable_solution.get_start(),
				variable_solution.get_end(),
			)

		return schedule


if __name__ == "__main__":
	#solver = MRCPSP_solver(jobs, duration, predecessors, resources, requests, shifts, orders)
	#solver.init_model()
	#solver.solve()
	#solver.print_solution()

	raise NotImplementedError("Do not run this module directly, use the MRCPSP_solver class implemented within!")
