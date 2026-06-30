import datetime
import logging

from util.constants import STARTING_DAY, BASIC_HOURS_PER_PERIOD, HOURS_IN_DAY, DAYS_IN_WEEK

__author__ = "Martina Kopecká"

from util.data_utils import read_int_array

DATE_STRING_FORMAT = "%m/%d"
TIME_STRING_FORMAT = "%H:%M"
DATE_TIME_FORMAT = "{} {}".format(DATE_STRING_FORMAT, TIME_STRING_FORMAT)

def next_calendar_start(calendar_start=STARTING_DAY):
    today = datetime.datetime.today()
    return datetime.datetime(year=today.year, month=today.month, day=today.day, hour=0) + datetime.timedelta(days=-today.weekday() + calendar_start, weeks=1)

def first_calendar_week(calendar_start=STARTING_DAY):
    start = next_calendar_start(calendar_start)
    return start + datetime.timedelta(days=DAYS_IN_WEEK)

def hours_to_date(hours: int):
    start = next_calendar_start()
    return start + datetime.timedelta(hours=hours)

def nth_day(day: int):
    start = next_calendar_start()
    return start + datetime.timedelta(days=day)

def next_date_with_day(date_day, hours = 0):
    """
    Parse shortcut format of date (D H) and get the nearest date after start of the scheduling period where the day is equal to :date_day.

    :param date_day: day part of the date
    :param hours: optional hours
    :return: nearest date after start of the scheduling period where the day part of the date is equal to :date_day
    """
    start = next_calendar_start()
    date = datetime.datetime(year=(start.year + 1 if start.month == 12 and date_day < start.day else start.year), month=(start.month % 12 + 1  if date_day < start.day else start.month), day=date_day, hour=hours % HOURS_IN_DAY)
    return (date - start).days * HOURS_IN_DAY + (hours - start.hour) % HOURS_IN_DAY

def time_difference_hours(date: datetime.datetime):
    start = next_calendar_start()
    return (date - start).days * HOURS_IN_DAY + (date.hour - start.hour) % HOURS_IN_DAY

def next_relative_date(date_day, hours = 0):
    start = next_calendar_start()
    return date_day * HOURS_IN_DAY + (hours - start.hour) % HOURS_IN_DAY


def format_to_hours_from_start(date, relative = False):
    valid_formats = ['%Y/%m/%d %H:%M', '%y/%m/%d %H:%M', '%d.%m.%Y %H:%M', '%d.%m.%y %H:%M', '%d.%m.%y', '%d.%m.%Y', '%y/%m/%d', '%Y/%m/%d', DATE_STRING_FORMAT, DATE_TIME_FORMAT]
    if not date:
        return None
    date = date.strip()
    try:
        for valid_format in valid_formats:
            try:
                date_parsed = datetime.datetime.strptime(date, valid_format)
                if valid_format in [DATE_STRING_FORMAT, DATE_TIME_FORMAT]:
                    start = next_calendar_start()
                    date_parsed = datetime.datetime(year=start.year if start.month <= date_parsed.month else start.year + 1, month=date_parsed.month, day=date_parsed.day, hour=date_parsed.hour, minute=date_parsed.minute)
                return time_difference_hours(date_parsed)
            except ValueError as e:
                print(e)
        line = read_int_array(date)
        if len(line) == 1:
            if relative:
                return next_relative_date(line[0])
            return next_date_with_day(line[0])
        elif len(line) == 2:
            if relative:
                return next_relative_date(line[0], line[1])
            return next_date_with_day(line[0], line[1])
    except Exception as e:
        logging.info(e)
        if date[0] == ':':
            return format_to_hours_from_start(date[1:], True)
        return None


class TimeFormatError(ValueError):
    def __init__(self, message):
        self.message = message

