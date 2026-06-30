import pandas as pd

__author__ = "Martina Kopecká"

def get_tables_diff(new_state, prev_state):
    """
    https://stackoverflow.com/questions/48647534/find-difference-between-two-data-frames

    :param new_state:
    :param prev_state:
    :return: differences in format [{"row": <id of row>, "column": <id of column>, "current_value": <current value>, "previous_value": <previous value>}]
    """
    df, df_previous = pd.DataFrame(data=new_state), pd.DataFrame(data=prev_state)

    df_mask = ~((df == df_previous) | ((df != df) & (df_previous != df_previous)))
    df_mask = df_mask.loc[df_mask.any(axis=1)]

    changes = []
    for idx, row in df_mask.iterrows():
        row_id = row.name
        row = row[row.eq(True)]

        for change in row.iteritems():
            changes.append(
                {
                    "row": row_id,
                    "column": change[0],
                    "current_value": df.at[row_id, change[0]],
                    "previous_value": df_previous.at[row_id, change[0]],
                }
            )
    return changes

def read_int_array(line: str):
    return list(map(lambda a: int(a.strip()), line.split()))

class Columns:
    UTILIZATION = 'Utilization'
    UTILIZATION_2 = 'Utilization_2'
    HOUR = 'Hour'
    DATE = 'Date'
    SOLUTION = 'Solution'
    COLOR = 'Color'
    TYPE, NONE, NON_TARDY, TARDY, JOB_ID, PART, PART_OF, JOB, NAME, START, END, DURATION, RESOURCE, REQUIREMENT, TARDINESS, DUE_DATE, COMPONENT, COMPONENT_ID, WEIGHTED_TARDINESS, WEIGHT, ID, SIZE, FINISHED, IN_PERIOD_TARDINESS, DEADLINE, RELEASE_DATE, RESOURCES, STARTED, ENDED, FAVORITE, END_LAST, HIDDEN_ID, SLACK, FINISHED_RAW, START_RAW, END_RAW = \
       'Type', 'None', 'Non-tardy', 'Tardy', 'Job_ID', 'Part', 'Part_Of', 'Job', 'Name', 'Start', 'End', 'Duration', 'Resource', 'Requirement', 'Tardiness', 'Due Date', 'Component', 'Order ID', 'Weighted_Tardiness', 'Weight', 'ID', 'Size', 'Finished', 'Period Tardiness', 'Deadline', 'Release Date', 'Resources', 'Started', 'Ended', 'Favorite', 'End_Last', 'Hidden_ID', 'Slack', 'Finished_raw', 'Start_raw', 'End_raw'
    BRANCH_TARDINESS, POTENTIAL = 'Branch_tardiness', 'Potential'

DATA_FRAME_RESOURCE_MODES = "DATA_FRAME_RESOURCE_MODES"
DATA_FRAME_RESOURCE_COLUMNS = "DATA_FRAME_RESOURCE_COLUMNS"
DATA_FRAME_RESOURCE_SELECTED_COLUMNS = "DATA_FRAME_RESOURCE_SELECTED_COLUMNS"
