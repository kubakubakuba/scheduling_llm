from docplex.cp.model import CpoModel, CpoStepFunction, INTERVAL_MAX

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


	def solve(self, time_limit=60, log_output=True):
		exec_params = {'TimeLimit': time_limit}

		if not log_output:
			exec_params['LogVerbosity'] = 'Quiet'

		self.sol = self.m.solve(TimeLimit=time_limit)

		if self.sol and self.sol.is_solution():
			return self.sol.get_objective_value()
		
		return None

	def print_solution(self):
		if not self.sol or not self.sol.is_solution():
			print("No solution found.")
			return
			
		for j in self.jobs:
			var_sol = self.sol.get_var_solution(self.job_vars[j])
			if var_sol:
				print(f"Job {j}: [{var_sol.get_start()}, {var_sol.get_end()}]")

	def get_schedule(self):
		if not self.sol or not self.sol.is_solution():
			return None

		schedule = {}
		
		for j in self.jobs:
			var_sol = self.sol.get_var_solution(self.job_vars[j])
			if var_sol:
				schedule[j] = (var_sol.get_start(), var_sol.get_end())
		
		return schedule


if __name__ == "__main__":
	#solver = MRCPSP_solver(jobs, duration, predecessors, resources, requests, shifts, orders)
	#solver.init_model()
	#solver.solve()
	#solver.print_solution()

	raise NotImplementedError("Do not run this module directly, use the MRCPSP_solver class implemented within!")
