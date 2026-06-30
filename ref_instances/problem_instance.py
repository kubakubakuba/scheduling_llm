import datetime
import json
import logging
import os
import random
from abc import abstractmethod
from copy import copy
from queue import Queue
from typing import List, Set

import pandas as pd

from util.constants import INSTANCES_FOLDER, DATA_FOLDER, SHIFT_HOURS, REGULAR_FREE_DAYS, DAYS_IN_WEEK, \
    VIS_FOLDER, get_mode_defaults
from util.data_utils import read_int_array, Columns
from util.time_utils import next_calendar_start, hours_to_date

__author__ = "Martina Kopecká"

ast = "************************************************************************\n"

class ProblemInstance:
    def __init__(self, instance_name: str or None, last_version: int or None = None):
        self.instance_name = instance_name
        self.text_file_location = get_file(instance_name)
        self.file_with_base_data = None
        self.initial_value_rnd = None
        self.project_count = None
        self.jobs = None
        self.horizon = None
        self.renewable_resources = None
        self.nonrenewable_resources = None
        self.doubly_constrained_resources = None
        self.projects = None
        self.precedence_relations = None
        self.requests_and_durations = None
        self.resource_availabilities = None
        self.due_dates = None
        self.finished_tasks = []
        self.resources_count = None
        self.resource_shift_modes = None
        self.resource_shift_modes_calculated = None
        self.release_dates = []
        self.deadlines = []
        self.precedence_graph = None
        self.component_order = None # Contains one node from each component, IDs starting from 0
        self.component_weights = None

        self.changes = []
        self.version_paths = []
        self.version_list = []
        self.version = None
        self.max_version = None
        if instance_name is not None:
            self.read_instance()
            self.precedence_graph = PrecedenceGraph(self)
            self.release_dates = [None for _ in range(self.precedence_graph.component_count)]
            self.deadlines = [None for _ in range(self.precedence_graph.component_count)]

            if len(self.changes) == 0:
                init_version = AddNewVersion(1, None)
                self.changes.append(init_version)
                init_version.apply(self)
                self.save_edited_instance()

        if last_version is not None:
            self._apply_version(last_version)

    @property
    def unsaved_changes(self):
        """
        :return: all changes that are not part of any version
        """
        starting_index = 0
        for i, change in enumerate(self.changes):
            if isinstance(change, AddNewVersion):
                starting_index = i + 1
        return self.changes[starting_index:]

    def apply_changes(self):
        """
        Create new solution with unsaved changes.
        """
        from config import Config
        change = AddNewVersion(self.max_version + 1, self.version)
        self.changes.append(change)
        self.max_version = self.max_version + 1
        self.save_edited_instance()
        Config.solve_instances(ProblemInstance(self.instance_name, self.max_version))

    def apply_unsaved_changes_locally(self):
        for change in self.unsaved_changes:
            change.apply(self)

    def revert_apply_unsaved_changes_locally(self):
        problem_instance = ProblemInstance(self.instance_name, self.version)
        problem_instance.changes = self.changes
        problem_instance.update_version_tree()
        return problem_instance

    def discard_changes(self):
        ending_index = 0
        for i, change in enumerate(self.changes):
            if self.max_version is not None and isinstance(change, AddNewVersion) and change.number == self.max_version:
                ending_index = i + 1
        self.changes = self.changes[:ending_index]
        self.save_edited_instance()


    def read_instance(self):
        """
        Benchmark file format is both machine- and human-readable.
        Here, we read the instance file and set the parameters of ProblemInstance instance.
        """
        text_file = open(self.text_file_location, "r")

        text_file.readline()  # skip the first *** line
        self.file_with_base_data = after_last_colon(text_file.readline())  # file with basedata name
        self.initial_value_rnd = int(after_last_colon(text_file.readline()))  # file with basedata name

        text_file.readline()  # skip the second *** line
        self.project_count = int(after_last_colon(text_file.readline()))  # projects
        self.jobs = int(after_last_colon(text_file.readline()))  # count of jobs + 2 (source and sink)
        self.horizon = int(after_last_colon(text_file.readline()))  # horizon
        text_file.readline()  # skip RESOURCES line
        self.renewable_resources = int(after_last_colon(text_file.readline()).split()[0])  # renewable resources
        self.nonrenewable_resources = int(after_last_colon(text_file.readline()).split()[0])  # non resources
        self.doubly_constrained_resources = int(after_last_colon(text_file.readline()).split()[0])  # DC resources
        self.resources_count = self.renewable_resources + self.nonrenewable_resources + self.doubly_constrained_resources
        text_file.readline()  # skip the third *** line
        text_file.readline()  # skip the PROJECT INFORMATION line
        text_file.readline()  # skip the PROJECT INFORMATION header

        # there can be more than just one project...
        self.projects = [_ for _ in range(self.project_count)]
        for i in range(self.project_count):
            project_information = read_int_array(text_file.readline())
            self.projects[i] = Project(project_information)
        text_file.readline()  # skip the fourth *** line

        text_file.readline()  # skip the PRECEDENCE RELATIONS line
        text_file.readline()  # skip the PRECEDENCE RELATIONS header
        self.precedence_relations = [_ for _ in range(self.jobs)]
        for i in range(self.jobs):
            information_line = read_int_array(text_file.readline())
            self.precedence_relations[i] = PrecedenceRelation(information_line)
        text_file.readline()  # skip the fifth *** line

        text_file.readline()  # skip the REQUESTS/DURATIONS line
        text_file.readline()  # skip the REQUESTS/DURATIONS header
        text_file.readline()  # skip the --- line
        # assign requests and durations to jobs
        self.requests_and_durations = [_ for _ in range(self.jobs)]
        for i in range(self.jobs):
            information_line = read_int_array(text_file.readline())
            self.requests_and_durations[i] = RequestAndDuration(information_line, self.renewable_resources, self.nonrenewable_resources)
        text_file.readline()  # skip the sixth *** line
        text_file.readline()  # skip the RESOURCEAVAILABILITIES line
        text_file.readline()  # skip the RESOURCEAVAILABILITIES header
        self.resource_availabilities = read_int_array(text_file.readline())
        text_file.readline()  # skip the seventh *** line
        if len(text_file.readline()) == 0:  # read empty line and end or start reading due dates
            return
        self.due_dates = [_ for _ in range(self.jobs)]
        for i in range(self.jobs):
            self.due_dates[i] = read_int_array(text_file.readline())[1]
        text_file.readline() # skip the eight *** line
        if len(text_file.readline()) == 0:  # read empty line and end or start reading finished tasks
            return
        read_int_array(text_file.readline())
        text_file.readline() # skip the *** line
        if len(text_file.readline()) == 0:  # read empty line and end or start reading components
            return
        line = text_file.readline()
        if line != '':
            self.component_order = read_int_array(line)
        text_file.readline() # skip the *** line
        if len(text_file.readline()) == 0:  # read empty line and end or start reading component weights
            return
        line = text_file.readline()
        if line != '':
            self.component_weights = read_int_array(line)
        text_file.readline() # skip the ninth *** line
        if len(text_file.readline()) == 0:  # read empty line and end or start reading shift modes
            return
        self.resource_shift_modes = [_ for _ in range(self.resources_count)]
        self.resource_shift_modes_calculated = [_ for _ in range(self.resources_count)]
        for i in range(self.resources_count):
            mode = read_int_array(text_file.readline())[1]
            self.resource_shift_modes[i] = mode
            self.resource_shift_modes_calculated[i] = ResourceMode(mode)
        text_file.readline() # skip the tenth *** line
        try:
            text_file = open(f"{self.text_file_location}.run", "r")
            changes_quantifier = read_int_array(text_file.readline())
            self.max_version = changes_quantifier[0]
            for _ in range(changes_quantifier[1]):
                self.changes.append(Change.parse(text_file.readline()))
        except FileNotFoundError:
            logging.debug("Run file not found")


    def to_string(self):
        return ast \
               + 'file with basedata            : {}\n'.format(self.file_with_base_data) \
               + 'initial value random generator: {}\n'.format(self.initial_value_rnd) \
               + ast \
               + 'projects                      :  {}\n'.format(self.project_count) \
               + 'jobs (incl. supersource/sink ):  {}\n'.format(self.jobs) \
               + 'horizon                       :  {}\n'.format(self.horizon) \
               + 'RESOURCES\n' \
               + '  - renewable                 :  {}   R\n'.format(self.renewable_resources) \
               + '  - nonrenewable              :  {}   N\n'.format(self.nonrenewable_resources) \
               + '  - doubly constrained        :  {}   D\n'.format(self.doubly_constrained_resources) \
               + ast \
               + 'PROJECT INFORMATION:\n' \
               + 'pronr.  #jobs rel.date duedate tardcost  MPM-Time\n' \
               + self.__projects_string() \
               + ast \
               + 'PRECEDENCE RELATIONS:\n' \
               + 'jobnr.    #modes  #successors   successors\n' \
               + self.__precedences_string() \
               + ast \
               + 'REQUESTS/DURATIONS:\n' \
               + 'jobnr. mode duration  R 1  R 2  R 3  R 4\n' \
               + '------------------------------------------------------------------------\n' \
               + self.__request_durations_string() \
               + ast \
               + 'RESOURCEAVAILABILITIES:\n' \
               + 'R ' + ' R '.join(map(lambda i: str(i + 1), range(self.renewable_resources))) + "\n" \
               + " ".join(map(lambda av: str(av), self.resource_availabilities)) + "\n" \
               + ( ast
               + 'DUE DATES:\n'
               + self.__due_dates_string_helper()
               + ast
               + 'FINISHED_TASKS: \n'
               + self.__finished_tasks_helper() if self.due_dates is not None else '') \
               + ( ast
               + 'COMPONENTS: \n'
               + ' '.join([str(node) for node in self.component_order]) + '\n' if self.component_order is not None else ''
               ) + (ast
                    + 'COMPONENT_WEIGHTS: \n'
                    + ' '.join([str(node) for node in self.component_weights]) + '\n' if self.component_weights is not None else ''
               )  \
               + ( ast
               + 'RESOURCE SHIFT MODES: \n'
               + self.__resource_modes_string_helper__() if self.resource_shift_modes is not None else ""
               )\

    def __finished_tasks_helper(self):
        string = ""
        for r in self.finished_tasks:
            string += "{} ".format(r + 1)
        return string + "\n"

    def __due_dates_string_helper(self):
        string = ""
        for i, d in enumerate(self.due_dates):
            string += "   {}   {} \n".format(i + 1, d)
        return string

    def __resource_modes_string_helper__(self):
        string = ""
        for i, d in enumerate(self.resource_shift_modes):
            string += "   {}   {}  \n".format(i + 1, d)
        return string

    def __changes_string_helper__(self):
        string = ""
        for change in self.changes:
            string += "{}\n".format(str(change))
        return string

    def __projects_string(self):
        string = ""
        for l in self.projects:
            string += "   {}     {}     {}      {}       {}       {}     \n".format(l.project_nr, l.jobs_count, l.release_date, l.due_date, l.tardiness_cost, l.mpm_time)
        return string

    def __precedences_string(self):
        string = ""
        for l in self.precedence_relations:
            string += "   {}     {}     {}     {} \n".format(l.job_nr, l.modes_count, l.successors_count, " ".join(map(lambda s: str(s), l.successors)))
        return string

    def __request_durations_string(self):
        string = ""
        for r in self.requests_and_durations:
            string += "  {}  {}  {}  {} \n".format(r.job_nr, r.mode, r.duration, "  ".join(map(lambda s: str(s), r.renewable_requests)))
        return string

    def __str__(self):
        return self.to_string()

    def _apply_version(self, last_version):
        version_list = [change for change in enumerate(self.changes) if isinstance(change[1], AddNewVersion)]
        tmp_version = version_list[last_version - 1]
        version_path = [tmp_version[1].number]
        while tmp_version[1].parent is not None:
            tmp_version = version_list[tmp_version[1].parent - 1]
            version_path.append(tmp_version[1].number)
        version_path.sort()
        row_numbers = [version_list[v - 2][0] + 1 if v > 2 else v - 1 for v in version_path]
        for row_number in row_numbers:
            changes = self.changes[row_number:]
            for change in changes:
                change.apply(self)
                if isinstance(change, AddNewVersion):
                    break

    def changes_str(self):
        return '{} {}\n'.format(self.max_version, len(self.changes)) + self.__changes_string_helper__() if len(self.changes) > 0 else ''

    @property
    def jobs_to_data_frame(self):
        components = self.precedence_graph
        data = [[job + 1, "Job #{}".format(job + 1), "{}h".format(self.requests_and_durations[job].duration), components.components[job], hours_to_date(self.due_dates[job])] for job in range(self.jobs)]
        data_frame = pd.DataFrame(data, columns=[Columns.ID, Columns.NAME, Columns.DURATION, Columns.COMPONENT, Columns.DUE_DATE])
        return data_frame

    def save_edited_instance(self):
        filename = f"{self.text_file_location}.run"
        with(open(filename, "w")) as f:
            f.write(self.changes_str())
            logging.info(f.name)

    def update_version_tree(self):
        version_list = [change for change in enumerate(self.changes) if isinstance(change[1], AddNewVersion)]
        version_paths = [[] for _ in range(self.max_version)]
        for version in range(self.max_version):
            tmp_version = version_list[version]
            version_paths[version] = [tmp_version[1].number]
            while tmp_version[1].parent is not None:
                tmp_version = version_list[tmp_version[1].parent - 1]
                version_paths[version].append(tmp_version[1].number)
            version_paths[version].sort()
        self.version_paths = version_paths
        self.version_list = version_list

    def compare(self, version_1, version_2):
        """
        Compare differences between two versions
        :param version_1:
        :param version_2:
        :return:
        """
        versions = [v for v in [version_1, version_2] if v is not None]
        if any([v > self.max_version for v in versions]):
            raise Exception(f"Version for compare is over {self.max_version}")
        changelogs = [[] for _ in [version_1, version_2]]
        if len(versions) == 0:
            return changelogs
        if len(versions) == 1:
            try:
                relevant_paths = [self.version_paths[versions[0] - 1]]
            except IndexError:
                relevant_paths = [[versions[0]]]
        else:
            relevant_paths = [sorted(list(set(self.version_paths[v[1] - 1]).difference(set(self.version_paths[v[0] - 1])))) for v in [list(reversed(versions)), versions]]
        for i, version in enumerate(versions):
            index_of = 0 if version == version_1 else 1
            rows = [self.version_list[v - 2][0] + 1 if v > 2 else v - 1 for v in relevant_paths[i]]
            for row_number in rows:
                changes = self.changes[row_number:]
                for change in changes:
                    changelogs[index_of].append(change)
                    if isinstance(change, AddNewVersion):
                        break
        if len(versions) == 2:
            tmp_changelog = [str(c) for c in changelogs[1]]
            none_indices = []
            for i, change in enumerate(changelogs[0]):
                try:
                    index = tmp_changelog.index(str(change))
                    tmp_changelog[index] = None
                    changelogs[1][index] = None
                    none_indices.append(i)
                except ValueError:
                    continue
            changelogs[0] = [c for i, c in enumerate(changelogs[0]) if i not in none_indices]
            changelogs[1] = [c for c in changelogs[1] if c is not None]
        return changelogs


class Project:
    def __init__(self, project_information):
        self.project_nr = project_information[0]
        self.jobs_count = project_information[1]
        self.release_date = project_information[2]
        self.due_date = project_information[3]
        self.tardiness_cost = project_information[4]
        self.mpm_time = project_information[5]

    def __str__(self):
        return "{} {} {} {} {} {}" \
            .format(self.project_nr, self.jobs_count, self.release_date, self.due_date, self.tardiness_cost, self.mpm_time)


class PrecedenceRelation:
    def __init__(self, precedence_relation):
        self.job_nr = precedence_relation[0]
        self.modes_count = precedence_relation[1]
        self.successors_count = precedence_relation[2]
        self.successors = precedence_relation[3:] # successors are indexed from 1

    def __str__(self):
        return "{} {} {} {}" \
            .format(self.job_nr, self.modes_count, self.successors_count, ' '.join([str(succ) for succ in self.successors]))


class RequestAndDuration:
    def __init__(self, request_duration, renewable_resources, nonrenewable_resources, doubly_constrained: int = 0):
        self.job_nr = request_duration[0]
        self.mode = request_duration[1]
        self.duration = request_duration[2]
        self.renewable_requests = request_duration[3:3 + renewable_resources]
        self.nonrenewable_requests = request_duration[4 + renewable_resources:4 + renewable_resources + nonrenewable_resources]
        self.doubly_constrained_requests = request_duration[5 + renewable_resources + nonrenewable_resources:]

    def __str__(self):
        return "{} {} {} {} {} {}" \
            .format(self.job_nr, self.mode, self.duration, ' '.join(str(r) for r in self.renewable_requests), ' '.join(str(r) for r in self.nonrenewable_requests), ' '.join(str(r) for r in self.doubly_constrained_requests))


class PrecedenceGraph:
    def __init__(self, problem_instance: ProblemInstance):
        self.problem_instance = problem_instance
        self.precedences: List[Set[PrecedenceGraph.Vertex or None]] = [set() for _ in range(self.problem_instance.jobs)]
        self.build()
        self.components = None
        self.component_count = 0
        self._component_order = problem_instance.component_order
        self.find_components()

    def build(self):
        """
        Build precedence graph
        """
        for (node, relations) in enumerate(self.problem_instance.precedence_relations):
            for successor in relations.successors:
                vertex = self.Vertex(node, successor - 1)
                self.precedences[successor - 1].add(vertex)
                self.precedences[node].add(vertex)

    def find_components(self):
        """
        Find SCCs in precedence graph.
        """
        unvisited = set(i for i in range(self.problem_instance.jobs)) # set of unvisited nodes, indexed from 0
        self.components: List[int or None] = [None for _ in range(self.problem_instance.jobs)]
        self.component_count = 0
        tmp_component_order = []
        while unvisited:
            start = random.choice(list(unvisited)) if self._component_order is None else self._component_order[self.component_count]
            tmp_component_order.append(start)
            queue = Queue()
            queue.put(start)
            while not queue.empty():
                node = queue.get()
                self.components[node] = self.component_count
                if not node in unvisited:
                    continue
                unvisited.remove(node)
                for vertex in self.precedences[node]:
                    second = vertex.second(node)
                    queue.put(second)
            self.component_count += 1
        self._component_order = tmp_component_order
        self.problem_instance.component_order = tmp_component_order
        return self.components

    def __filter_component_containing__(self, node: int):
        return filter(lambda i: self.components[i] == self.components[node], range(len(self.components)))

    def component_of(self, node: int):
        return set(self.__filter_component_containing__(node))

    def _recursive_topological_sort(self, node, visited, stack):
        visited[node] = True
        for vertex in self.precedences[node]:
            if vertex.n_1 == node and not visited[vertex.n_2]:
                self._recursive_topological_sort(vertex.n_2, visited, stack)
        stack.append(node)

    def topologically_sorted_component_of(self, node: int):
        nodes = list(self.__filter_component_containing__(node))
        visited = [False for _ in range(len(self.components))]
        stack = []
        for n in nodes:
            if not visited[n]:
                self._recursive_topological_sort(n, visited, stack)
        return stack[::-1]

    def nth_topologically_sorted_component(self, n: int):
        node = self.components.index(n)
        return self.topologically_sorted_component_of(node)

    def critical_path_length(self, i: int):
        component = self.nth_topologically_sorted_component(i)
        if len(component) <= 1:
            return self.problem_instance.requests_and_durations[component[0]].duration
        sources = []
        for n in component:
            if len(self.predecessors_of(n)) == 0:
                sources.append(n)
        max_len = 0
        for source in sources:
            max_len = max(max_len, max(self.longest_paths(source, component)))
        return max_len

    def longest_paths(self, source, component):
        infty = float('-inf')
        dist = [infty] * self.problem_instance.jobs
        dist[source] = self.problem_instance.requests_and_durations[source].duration

        found_source = False
        for v in component:
            if v == source:
                found_source = True
            if not found_source:
                continue
            for w in self.successors_of(v):
                if dist[w] <= dist[v] + self.problem_instance.requests_and_durations[w].duration:
                    dist[w] = dist[v] + self.problem_instance.requests_and_durations[w].duration
        return dist

    def predecessors_of(self, n: int):
        return list(map(lambda w: w.n_1, filter(lambda x: x.n_2 == n, self.precedences[n])))

    def successors_of(self, n: int):
        return list(map(lambda w: w.n_2, filter(lambda x: x.n_1 == n, self.precedences[n])))

    class Vertex:
        def __init__(self, n_1: int, n_2: int):
            self.n_1 = n_1
            self.n_2 = n_2

        def __str__(self):
            return "{} {}".format(self.n_1, self.n_2)

        def second(self, node: int):
            return self.n_1 if node == self.n_2 else self.n_2


class ResourceMode:
    def __init__(self, default_mode):
        self.mode_defaults = get_mode_defaults(default_mode)
        self._modified_days = {} # key: i for i-th day, value: None if i-th day is not a working day, [start, end] if i-th day is a working day

    def modify_nth_day(self, n: int, start: int or None=None, end: int or None=None, remove: bool=False):
        """
        :param n: day
        :param start: starting hours
        :param end: ending hours
        :param remove: Indicates whether this working day should be removed. If set to False, the working day can be added (either with start and end hours or default)
        """
        working_hours = copy(self.get_working_hours_on_nth_day(n))
        if not working_hours:
            working_hours = self.mode_defaults[SHIFT_HOURS]

        if start is not None:
            working_hours[0] = start
        if end is not None:
            working_hours[1] = end

        if remove:
            working_hours = None
        self._modified_days[n] = working_hours

    def is_nth_day_working(self, n):
        """
        :param n: day
        :return: True if n-th day is a working day, False if n-th day is not a working day
        """
        return self.get_working_hours_on_nth_day(n) is not None

    def get_working_hours_on_nth_day(self, n):
        """
        Get start and end of shifts on n-th day
        :param n: day
        :return: None if n-th day is not a working day, [start, end] if n-th day is a working day
        """
        if n < 0:
            return None
        if n in self._modified_days:
            return self._modified_days[n]
        else:
            return self.mode_defaults[SHIFT_HOURS] if n % DAYS_IN_WEEK not in self.mode_defaults[REGULAR_FREE_DAYS] else None

    def get_balance_on_nth_day(self, n):
        """
        Compare number of working hours between default setting of resource and customized setting.

        :param n: day
        :return: number of working hours added/removed by custom setting
        """
        if n % DAYS_IN_WEEK in self.mode_defaults[REGULAR_FREE_DAYS]:
            working_hours = self.get_working_hours_on_nth_day(n)
            if working_hours:
                return working_hours[1] - working_hours[0]
            return 0
        default_start, default_end = self.mode_defaults[SHIFT_HOURS]
        working_hours = self.get_working_hours_on_nth_day(n)
        if working_hours:
            return default_start - working_hours[0] + working_hours[1] - default_end
        return default_start - default_end

    def number_of_working_days_until(self, until):
        """

        :param until: Order number of the last day taken into account
        :return: Number of working days in scheudling period until some upper bound
        """
        counter = 0
        for i in range(until + 1):
            if self.is_nth_day_working(i):
                counter += 1
        return counter

(
    ADD_NEW_VERSION,
    RESOURCE_WORKING_HOURS,
    ADD_IRREGULAR_WORKING_DAY,
    REMOVE_WORKING_DAY,
    ADD_RELEASE_DATE,
    REMOVE_RELEASE_DATE,
    ADD_DEADLINE,
    REMOVE_DEADLINE,
    CHANGE_WEIGHT
) = range(9)

class Change:
    @property
    @abstractmethod
    def type(self):
        pass

    @property
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def __str__(self):
        pass

    @abstractmethod
    def apply(self, problem_instance: ProblemInstance):
        pass

    @property
    @abstractmethod
    def human_readable_format(self):
        pass

    @property
    @abstractmethod
    def human_readable_tooltip(self):
        pass

    @staticmethod
    def parse(change: str):
        return {
            str(ADD_NEW_VERSION): lambda variable: AddNewVersion.parse(variable),
            str(RESOURCE_WORKING_HOURS): lambda variable: ResourceWorkingHoursChange.parse(variable),
            str(ADD_IRREGULAR_WORKING_DAY): lambda variable: AddWorkingDay.parse(variable),
            str(REMOVE_WORKING_DAY): lambda variable: RemoveWorkingDay.parse(variable),
            str(ADD_RELEASE_DATE): lambda variable: AddReleaseDate.parse(variable),
            str(REMOVE_RELEASE_DATE): lambda variable: RemoveReleaseDate.parse(variable),
            str(ADD_DEADLINE): lambda variable: AddDeadline.parse(variable),
            str(REMOVE_DEADLINE): lambda variable: RemoveDeadline.parse(variable),
            str(CHANGE_WEIGHT): lambda variable: WeightChange.parse(variable)
        }[change.split('*')[0]](change.strip())


class AddNewVersion(Change):
    @property
    def human_readable_tooltip(self):
        return f"Parent is {self.parent}"

    @property
    def human_readable_format(self):
        return f"Added version {self.number}"

    def __init__(self, number: int, parent: int or None):
        self.number = number
        self.parent = parent

    @property
    def type(self):
        return ADD_NEW_VERSION

    @property
    def name(self):
        return "AddVersion_{}".format(self.number)

    def __str__(self):
        return f"{self.type}*{self.number}*{self.parent if self.parent is not None else ''}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.version = self.number
        problem_instance.max_version = max(self.number, problem_instance.max_version if problem_instance.max_version is not None else 0)

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return AddNewVersion(int(change_list[1]), None if change_list[2] == '' else int(change_list[2]))


class ResourceWorkingHoursChange(Change):
    @property
    def human_readable_tooltip(self):
        return f"Working from {self.start_time if self.start_time else 'unchanged'} to {self.end_time if self.end_time else 'unchanged'}"

    @property
    def human_readable_format(self):
        return f"Changed working hours on R{self.resource + 1}"

    def __init__(self, resource: int, relative_date: int, start_time: int or None, end_time: int or None):
        self.resource = resource
        self.relative_date = relative_date
        self.start_time = start_time
        self.end_time = end_time

    @property
    def type(self):
        return RESOURCE_WORKING_HOURS

    @property
    def name(self):
        return "ChangeHoursOnR{}".format(self.resource + 1)

    def __str__(self):
        return f"{self.type}*{self.resource}*{self.relative_date}*{self.start_time if self.start_time is not None else ''}*{self.end_time if self.end_time is not None else ''}"

    def apply(self, problem_instance: ProblemInstance):
        if self.start_time is not None:
            problem_instance.resource_shift_modes_calculated[self.resource].modify_nth_day(self.relative_date, start=self.start_time)
        if self.end_time is not None:
            problem_instance.resource_shift_modes_calculated[self.resource].modify_nth_day(self.relative_date, end=self.end_time)

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return ResourceWorkingHoursChange(int(change_list[1]), int(change_list[2]), None if change_list[3] == '' else int(change_list[3]), None if change_list[4] == '' else int(change_list[4]))


class AddWorkingDay(Change):
    @property
    def human_readable_tooltip(self):
        return f"Working on {next_calendar_start() + datetime.timedelta(days=int(self.relative_date))}"

    @property
    def human_readable_format(self):
        return f"Added :{self.relative_date} as working day on R{self.resource + 1}"

    def __init__(self, resource: int, relative_date: int):
        self.resource = resource
        self.relative_date = relative_date

    @property
    def type(self):
        return ADD_IRREGULAR_WORKING_DAY

    @property
    def name(self):
        return "AddWorkingDayOn{}".format(self.resource + 1)

    def __str__(self):
        return f"{self.type}*{self.resource}*{self.relative_date}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.resource_shift_modes_calculated[self.resource].modify_nth_day(self.relative_date)

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return AddWorkingDay(int(change_list[1]), int(change_list[2]))

class RemoveWorkingDay(Change):
    @property
    def human_readable_tooltip(self):
        return f"Not working on {next_calendar_start() + datetime.timedelta(days=int(self.relative_date))}"

    @property
    def human_readable_format(self):
        return f"Removed :{self.relative_date} as working day on R{self.resource + 1}"

    def __init__(self, resource: int, relative_date: int):
        self.resource = resource
        self.relative_date = relative_date

    @property
    def type(self):
        return REMOVE_WORKING_DAY

    @property
    def name(self):
        return "RemoveWorkingDayFrom{}".format(self.resource+1)

    def __str__(self):
        return f"{self.type}*{self.resource}*{self.relative_date}"


    def apply(self, problem_instance: ProblemInstance):
        problem_instance.resource_shift_modes_calculated[self.resource].modify_nth_day(self.relative_date, remove=True)

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return RemoveWorkingDay(int(change_list[1]), int(change_list[2]))

class AddReleaseDate(Change):
    @property
    def human_readable_tooltip(self):
        return f"Release date is {hours_to_date(self.release_date)}"

    @property
    def human_readable_format(self):
        return f"Added release date to component #{self.component + 1}"

    def __init__(self, component: int, release_date: int):
        self.component = component
        self.release_date = release_date

    @property
    def type(self):
        return ADD_RELEASE_DATE

    @property
    def name(self):
        return "AddReleaseOn{}".format(self.component + 1)

    def __str__(self):
        return f"{self.type}*{self.component}*{self.release_date}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.release_dates[self.component] = self.release_date

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return AddReleaseDate(int(change_list[1]), int(change_list[2]))

class RemoveReleaseDate(Change):
    @property
    def human_readable_tooltip(self):
        return f"Release date was removed"

    @property
    def human_readable_format(self):
        return f"Removed release date from {self.component + 1}"

    def __init__(self, component):
        self.component = component

    @property
    def type(self):
        return REMOVE_RELEASE_DATE

    @property
    def name(self):
        return "RemoveReleaseFrom{}".format(self.component + 1)

    def __str__(self):
        return f"{self.type}*{self.component}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.release_dates[self.component] = None

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return RemoveReleaseDate(int(change_list[1]))


class AddDeadline(Change):
    @property
    def human_readable_tooltip(self):
        return f"Deadline is on {hours_to_date(self.deadline)}"

    @property
    def human_readable_format(self):
        return f"Added deadline to component #{self.component + 1}"

    def __init__(self, component: int, deadline: int):
        self.component = component
        self.deadline = deadline

    @property
    def type(self):
        return ADD_DEADLINE

    @property
    def name(self):
        return "AddDeadlineOn{}".format(self.component + 1)

    def __str__(self):
        return f"{self.type}*{self.component}*{self.deadline}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.deadlines[self.component] = self.deadline

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return AddDeadline(int(change_list[1]), int(change_list[2]))

class RemoveDeadline(Change):
    @property
    def human_readable_tooltip(self):
        return f"Deadline was removed"

    @property
    def human_readable_format(self):
        return f"Removed deadline from component {self.component}"

    def __init__(self, component: int):
        self.component = component

    @property
    def type(self):
        return REMOVE_DEADLINE

    @property
    def name(self):
        return "RemoveDeadlineOn{}".format(self.component + 1)

    def __str__(self):
        return f"{self.type}*{self.component}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.deadlines[self.component] = None

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return RemoveDeadline(int(change_list[1]))

class WeightChange(Change):
    @property
    def human_readable_tooltip(self):
        return f"Weight is {self.weight}"

    @property
    def human_readable_format(self):
        return "Change weight of component #{}".format(self.component + 1)

    def __init__(self, component: int, weight: int):
        self.component = component
        self.weight = weight

    @property
    def type(self):
        return CHANGE_WEIGHT

    @property
    def name(self):
        return "ChangeWeightOf{}".format(self.component + 1)

    def __str__(self):
        return f"{self.type}*{self.component}*{self.weight}"

    def apply(self, problem_instance: ProblemInstance):
        problem_instance.component_weights[self.component] = self.weight

    @staticmethod
    def parse(change: str):
        change_list = change.split('*')
        return WeightChange(int(change_list[1]), int(change_list[2]))

# Quick solution to get the correct instance file with different callers.
def get_file(instance_name):
    caller = os.getcwd().split("/")
    if caller[len(caller) - 1] in [VIS_FOLDER, INSTANCES_FOLDER]:
        file = "../{}/{}/{}".format(INSTANCES_FOLDER, DATA_FOLDER, instance_name)
    else:
        file = "{}/{}/{}".format(INSTANCES_FOLDER, DATA_FOLDER, instance_name)
    return file

def after_last_colon(line: str):
    return line.split(":")[-1].strip()
