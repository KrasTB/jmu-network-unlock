# -*- coding: utf-8 -*-
"""Shared campus-network schedule rules."""
import datetime
import os

from package_runtime import data_dir
BASE = str(data_dir())
HOLIDAY_FILE = os.path.join(BASE, "holidays.txt")
RECOVER_HOUR = 6
PREP_MINUTES = 8


def load_holidays(path=HOLIDAY_FILE):
    dates = set()
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for raw in f:
                value = raw.split("#", 1)[0].strip()
                if not value:
                    continue
                try:
                    dates.add(datetime.date.fromisoformat(value))
                except ValueError:
                    pass
    except OSError:
        pass
    return dates


def is_holiday(day, holidays=None):
    return day in (holidays if holidays is not None else load_holidays())


def cutoff(day):
    """Return the regular cutoff datetime for a date, or None on a holiday."""
    holidays = load_holidays()
    if day in holidays or day + datetime.timedelta(days=1) in holidays:
        return None
    # Monday-Thursday 23:00; Friday-Sunday 24:00.
    hour = 23 if day.weekday() <= 3 else 24
    return datetime.datetime.combine(day, datetime.time(0)) + datetime.timedelta(hours=hour)


def is_blackout(dt=None):
    dt = dt or datetime.datetime.now()
    holidays = load_holidays()
    if dt.date() in holidays:
        return False
    if dt.hour < RECOVER_HOUR:
        # The interval after midnight belongs to the previous evening.
        previous = cutoff(dt.date() - datetime.timedelta(days=1))
        return bool(previous and dt >= previous)
    boundary = cutoff(dt.date())
    return bool(boundary and dt >= boundary)


def should_prepare_bypass(dt=None):
    """Whether to move to bypass before the cutoff, with no holiday eve switch."""
    dt = dt or datetime.datetime.now()
    boundary = cutoff(dt.date())
    if not boundary:
        return False
    delta = (boundary - dt).total_seconds()
    return 0 < delta <= PREP_MINUTES * 60


def should_run(dt=None):
    dt = dt or datetime.datetime.now()
    if should_prepare_bypass(dt) or is_blackout(dt):
        return dt.minute % 2 == 0
    return is_carrier_recovery_time(dt)


def is_carrier_recovery_time(dt=None):
    """Half-hour daytime slots, with a small grace window for task startup."""
    dt = dt or datetime.datetime.now()
    return (dt.hour >= RECOVER_HOUR and dt.minute % 30 < 2 and
            not is_blackout(dt) and not should_prepare_bypass(dt))
