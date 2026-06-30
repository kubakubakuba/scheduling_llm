import glob
import random
import sys
from optparse import OptionParser
from random import Random

import numpy as np

sys.path.append("../")

from problem_instance import ProblemInstance, Project, PrecedenceRelation, RequestAndDuration, PrecedenceGraph
from util.constants import DATA_FOLDER, HOURS_IN_DAY, DUE_DATES_PER_DAY

__author__ = "Martina Kopecká"

def generate_from_instance(problem_instance: ProblemInstance, name: str, mean, variance, step=0):
    """
    Generate a *.rp instance file from any problem instance
    :param problem_instance: problem instance to be used
    :param name: base name for the new instance
    :param mean: mean parameter for the random variable
    :param variance: variance parameter for the random variable
    """
    generator = InstanceGenerator(problem_instance)
    generator._scale_up_times()

    if problem_instance.precedence_graph is None:
        problem_instance.precedence_graph = PrecedenceGraph(problem_instance)

    if problem_instance.precedence_graph.component_count == 1:
        generator._relax_precedence_relations()
        problem_instance.component_order = None
        problem_instance.precedence_graph = PrecedenceGraph(problem_instance)

    generator.generate_due_dates(mean, variance, step)

    with(open(_edited_instance_filename(name), "w")) as f:
        f.write(str(generator.problem_instance))
        print(f.name)

def merge_instances(instances):
    """
    Merge multiple problem instances into one
    :param instances: list of problem instances to be merged
    :return: `ProblemInstance` object where the activities come from multiple original instances
    """
    merged_instance = ProblemInstance(None)
    loaded_instances = [ProblemInstance(instance) for instance in instances]
    _weights = []
    for problem_instance in loaded_instances:
        generator = InstanceGenerator(problem_instance)
        generator._relax_precedence_relations()
        for c in range(generator.problem_instance.jobs):
            _weights.append(random.randint(3, 6))

    merged_instance.instance_name = " + ".join(list(map(lambda instance: instance.instance_name, loaded_instances)))
    merged_instance.initial_value_rnd = 0
    merged_instance.project_count = max([instance.project_count for instance in loaded_instances])
    merged_instance.jobs = sum([instance.jobs for instance in loaded_instances])
    merged_instance.horizon = sum([instance.horizon for instance in loaded_instances])
    merged_instance.renewable_resources = max([instance.renewable_resources for instance in loaded_instances])
    merged_instance.nonrenewable_resources = max([instance.nonrenewable_resources for instance in loaded_instances])
    merged_instance.doubly_constrained_resources = max([instance.doubly_constrained_resources for instance in loaded_instances])
    merged_instance.resources_count = merged_instance.renewable_resources + merged_instance.nonrenewable_resources + merged_instance.doubly_constrained_resources
    merged_instance.projects = [_ for _ in range(merged_instance.project_count)]
    for i in range(merged_instance.project_count):
        projects = [instance.projects[i] for instance in loaded_instances if instance.project_count > i]
        info = [i + 1, sum([project.jobs_count for project in projects]), max([project.release_date for project in projects]), min([project.due_date for project in projects]), max([project.tardiness_cost for project in projects]), max([project.mpm_time for project in projects])]
        merged_instance.projects[i] = Project(info)
    job_plus = 0
    merged_instance.precedence_relations = [i for i in range(merged_instance.jobs)]

    merged_instance.requests_and_durations = [_ for _ in range(merged_instance.jobs)]
    for i, instance in enumerate(loaded_instances):
        for r, relation in enumerate(instance.precedence_relations):
            information_line = [relation.job_nr + job_plus, relation.modes_count, relation.successors_count] + [s + job_plus for s in relation.successors]
            merged_instance.precedence_relations[r + job_plus] = PrecedenceRelation(information_line)
        for r, request in enumerate(instance.requests_and_durations):
            information_line = [request.job_nr + job_plus, request.mode, request.duration] + request.renewable_requests + [0 for _ in range(max(0, merged_instance.renewable_resources - instance.renewable_resources))] + request.nonrenewable_requests + [0 for _ in range(max(0, merged_instance.nonrenewable_resources - instance.nonrenewable_resources))] + request.doubly_constrained_requests + [0 for _ in range(max(0, merged_instance.doubly_constrained_resources - instance.doubly_constrained_resources))]
            merged_instance.requests_and_durations[r + job_plus] = RequestAndDuration(information_line, merged_instance.renewable_resources, merged_instance.nonrenewable_resources, merged_instance.doubly_constrained_resources)
        job_plus += instance.jobs

    merged_instance.resource_availabilities = [0 for _ in range(merged_instance.resources_count)]
    for i, _ in enumerate(merged_instance.resource_availabilities):
        merged_instance.resource_availabilities[i] = max([instance.resource_availabilities[i] for instance in loaded_instances if instance.resources_count > i])

    precedence_graph = PrecedenceGraph(merged_instance)
    merged_instance.component_weights = [_weights[node] for node in precedence_graph.problem_instance.component_order]

    return merged_instance

def _edited_instance_filename(instance_name: str):
    files = glob.glob("{}/{}*.rp".format(DATA_FOLDER, instance_name))
    sequence_number = 0 if len(files) == 0 else (max(list(map(lambda f: int(f.split(".sm_")[1].split(".")[0]), files))) + 1)
    return "{}/{}_{}.rp".format(DATA_FOLDER, instance_name, sequence_number)


class InstanceGenerator:
    def __init__(self, problem_instance: ProblemInstance):
        self.problem_instance = problem_instance
        self.finished_tasks = []

    def _scale_up_times(self, factor_max: float = 2.0, factor_min: float = 1.4):
        factor = Random().randint(round(factor_min * 10), round(factor_max * 10))
        for rd in self.problem_instance.requests_and_durations:
            rd.duration = round(factor * 0.1 * rd.duration)
        self.problem_instance.horizon = sum([rd.duration for rd in self.problem_instance.requests_and_durations])

    def _relax_precedence_relations(self, component_no: int = 3):
        _out = "out"; _in = "in"; _out_set = "out_set"; _in_set = "in_set"
        precedence_graph = self.problem_instance.precedence_graph
        if component_no > self.problem_instance.jobs:
            raise Exception("Cannot divide problem instance")
        elif precedence_graph.component_count > 1:
            raise Exception("Precedence graph already divided")

        rnd = random.Random()
        unvisited = set(i for i in range(self.problem_instance.jobs))
        components = [[] for _ in range(component_no)]
        neighbours = [{_out_set: set(), _in_set: set()} for _ in range(component_no)]

        finished_components = set()

        def add_to_component(c, elem):
            components[c].append(elem)
            neighbours[c][_out_set] = neighbours[c][_out_set].union(set(s for s in precedence_graph.successors_of(elem)))
            neighbours[c][_in_set] = neighbours[c][_in_set].union(set(s for s in precedence_graph.predecessors_of(elem)))
            unvisited.remove(elem)

        for c in range(component_no):
            elem = rnd.choice(range(self.problem_instance.jobs))
            while elem not in unvisited:
                elem = rnd.choice(range(self.problem_instance.jobs))
            add_to_component(c, elem)

        while len(finished_components) != component_no:
            for c in range(component_no):
                if c in finished_components:
                    continue
                if unvisited.intersection(neighbours[c][_out_set]):
                    elem = rnd.choices(list(unvisited.intersection(neighbours[c][_out_set])))[0]

                    add_to_component(c, elem)
                elif unvisited.intersection(neighbours[c][_in_set]):
                    elem = rnd.choices(list(unvisited.intersection(neighbours[c][_in_set])))[0]
                    add_to_component(c, elem)
                else:
                    finished_components.add(c)

        component_sets = [set(component) for component in components]

        for precedence in self.problem_instance.precedence_relations:
            component = None
            for i, c_set in enumerate(component_sets):
                if (precedence.job_nr - 1) in c_set:
                    component = i
                    break
            new_successors = []; new_successor_count = 0

            for successor in precedence.successors:
                if (successor - 1) in component_sets[component]:
                    new_successors.append(successor)
                    new_successor_count += 1
            precedence.successors = new_successors
            precedence.successors_count = new_successor_count
        return self.problem_instance

    def generate_due_dates(self, mean, variance, step):
        precedence_graph = self.problem_instance.precedence_graph
        due_dates = [0 for _ in range(self.problem_instance.jobs)]
        cumulative_due_date = 0

        for i in range(precedence_graph.component_count):
            cumulative_due_date = self._generate_due_dates_helper(i, due_dates, precedence_graph, cumulative_due_date, mean, variance, step, h_i_fact=(1.3 - i / precedence_graph.component_count))
        self._generate_shift_modes()

    def _generate_shift_modes(self):
        self.problem_instance.resource_shift_modes = [random.randint(1, 2) for _ in range(self.problem_instance.resources_count)]

    def _generate_due_dates_helper(self, i, due_dates, precedence_graph, cumulative_h_i, mean, variance, step, h_i_fact: float = 1.0):
        def round_due_date(due_date):
            offsets = round(HOURS_IN_DAY / DUE_DATES_PER_DAY)
            difference = due_date % offsets
            return int((-difference if difference / offsets < 0.5 else offsets - difference) + due_date)
        component = precedence_graph.nth_topologically_sorted_component(i)
        cumulative_h_i += precedence_graph.critical_path_length(i) * h_i_fact
        h_i = cumulative_h_i
        mean += step
        x_i = self._random_variable_due_date(mean, variance)

        for i, c in enumerate(component):
            due_dates[c] = round_due_date(h_i + x_i)
        self.problem_instance.due_dates = due_dates
        return cumulative_h_i

    @staticmethod
    def _random_variable_due_date(mean, variance):
        return round(np.random.normal(mean, variance))

if __name__ == '__main__':
    random_mean, random_variance, random_step = -4, 10, 0
    parser = OptionParser()
    parser.add_option("-m", "--mean", help="Sets mean for random variable", default=random_mean)
    parser.add_option("-v", "--variance", help="Sets variance for random variable", default=random_variance)
    parser.add_option("-s", "--step", help="Sets step for random variable", default=random_step)

    (opts, args) = parser.parse_args()

    random_mean = int(opts.mean)
    random_variance = int(opts.variance)
    random_step = int(opts.step)

    new_instance = merge_instances(args)
    generate_from_instance(new_instance, args[0], random_mean, random_variance)
