import calendar

__author__ = "Martina Kopecká"

BASIC_CELL_WIDTH = 60
BASIC_CELL_HEIGHT = 36

NUMBER_OF_CAPACITY_VIZ_MODES = 3
MODE_1, MODE_2, MODE_3 = range(1, NUMBER_OF_CAPACITY_VIZ_MODES + 1)

DATA_FOLDER = "data"
INSTANCES_FOLDER = "instances"
VIS_FOLDER = "visualizations"

DAYS_IN_WEEK = 7
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
HOURS_IN_DAY = 24

BASIC_SCHEDULING_PERIOD_WEEKS = 2
BASIC_SCHEDULING_PERIOD_DAYS = DAYS_IN_WEEK * BASIC_SCHEDULING_PERIOD_WEEKS
BASIC_HOURS_PER_PERIOD = BASIC_SCHEDULING_PERIOD_DAYS * HOURS_IN_DAY

SCHEDULING_PERIOD_DAYS = DAYS_IN_WEEK * BASIC_SCHEDULING_PERIOD_WEEKS

DUE_DATES_PER_DAY = 2
GOOD_UTILIZATION_THRESHOLD = 0.8
LOW_UTILIZATION_THRESHOLD = 0.4

STARTING_DAY = calendar.MONDAY
REGULAR_FREE_DAYS_LIST = [calendar.SATURDAY, calendar.SUNDAY]

SHIFT_HOURS = "shift_hours"; START = "start"; END = "end"; REGULAR_FREE_DAYS = "free_days"; IRREGULAR_WORKING_DAYS = "irregular_working_days"; IRREGULAR_FREE_DAYS = "irregular_free_days"; WORKING_HOURS = "working_hours"

RESOURCE_MODE_ONE_SHIFT, RESOURCE_MODE_TWO_SHIFTS = 1, 2

def get_mode_defaults(mode: int):
    """
    For mode each default mode (1 or 2 given by the number of shifts per day), get the default working times
    :param mode:
    :return: The default working hours in format {SHIFT_HOURS: [<from>, <to>], REGULAR_FREE_DAYS: [<list with numbers representing weekdays, 0=Monday, 6=Sunday>]}
    """
    if mode not in [RESOURCE_MODE_ONE_SHIFT, RESOURCE_MODE_TWO_SHIFTS]:
        raise ValueError(f'Only shift modes {RESOURCE_MODE_ONE_SHIFT} and {RESOURCE_MODE_TWO_SHIFTS} exist')
    if mode == RESOURCE_MODE_ONE_SHIFT:
        return {SHIFT_HOURS: [8, 16], REGULAR_FREE_DAYS: REGULAR_FREE_DAYS_LIST}
    if mode == RESOURCE_MODE_TWO_SHIFTS:
        return {SHIFT_HOURS: [6, 22], REGULAR_FREE_DAYS: REGULAR_FREE_DAYS_LIST}
