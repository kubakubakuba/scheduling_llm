from docplex.cp.model import CpoModel

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

			for j in self.jobs:
				req_amount = self.req.get((j, k), 0)

				if req_amount > 0:
					usage += self.m.pulse(self.job_vars[j], req_amount)

			for start, end, cap in self.shifts[k]:
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
	#0 is source, 5 is sink
	jobs = [0, 1, 2, 3, 4, 5]

	duration = {
		0: 0,
		1: 10,
		2: 8,
		3: 15,
		4: 5,
		5: 0
	}

	predecessors = {
		0: [],
		1: [0],
		2: [0],
		3: [1],
		4: [2],
		5: [3, 4]
	}

	resources = ['R1', 'R2']

	requests = {
		(1, 'R1'): 2,
		(1, 'R2'): 0,

		(2, 'R1'): 1,
		(2, 'R2'): 1,

		(3, 'R1'): 0,
		(3, 'R2'): 2,

		(4, 'R1'): 1,
		(4, 'R2'): 1
	}

	shifts = {
		'R1': [
			(0, 16, 2),
			(16, 24, 0),
			(24, 40, 2),
			(40, 48, 0),
			(48, 100, 2)
		],
		'R2': [
			(0, 20, 2),
			(20, 24, 0),
			(24, 44, 2),
			(44, 48, 0),
			(48, 100, 2)
		]
	}

	orders = [
		{
			'component_id': 'Order_A',
			'sink_job': 4,
			'due_date': 15,
			'weight': 2
		},
		{
			'component_id': 'Order_B',
			'sink_job': 5,
			'due_date': 30,
			'weight': 5
		}
	]

	solver = RCPSP_solver(jobs, duration, predecessors, resources, requests, shifts, orders)

	solver.init_model()

	solver.solve()

	solver.print_solution()

