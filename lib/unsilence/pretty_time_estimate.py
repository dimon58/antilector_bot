from datetime import timedelta

from prettytable import SINGLE_BORDER, PrettyTable

from .intervals.time_calculations import TimeData


def format_timedelta(seconds: float) -> str:
    """
    Generates a pretty time representation for seconds (format: hour:minute:second)
    :param seconds: Amount of seconds (can be negative)
    :return: String representation
    """
    if seconds < 0:
        return f"-{timedelta(seconds=-seconds)}"

    return str(timedelta(seconds=seconds))


def pretty_time_estimate(time_data: TimeData) -> PrettyTable:
    """
    Generates a rich.table.Table object from the time_data dict (from lib.Intervals.TimeCalculations.calculate_time)

    modified unsilence.command_line.PrettyTimeEstimate.pretty_time_estimate for use prettytable instead of rich.Table
    :param time_data: time_data dict (from lib.Intervals.TimeCalculations.calculate_time)
    :return: rich.table.Table object
    """
    table = PrettyTable(field_names=("Type", "Before", "After", "Difference"))
    table.set_style(SINGLE_BORDER)
    table.align = "l"

    reorderer_time_data = {"all": {}, "audible": {}, "silent": {}}
    for column, row_with_values in time_data.items():
        for row, values in row_with_values.items():
            time_delta = format_timedelta(round(values[0]))
            reorderer_time_data[row][column] = f"{time_delta} ({round(values[1] * 100, 1)}%)"

    table.add_row(
        (
            "Combined",
            reorderer_time_data["all"]["before"],
            reorderer_time_data["all"]["after"],
            reorderer_time_data["all"]["delta"],
        )
    )

    table.add_row(
        (
            "Audible",
            reorderer_time_data["audible"]["before"],
            reorderer_time_data["audible"]["after"],
            reorderer_time_data["audible"]["delta"],
        )
    )

    table.add_row(
        (
            "Silent",
            reorderer_time_data["silent"]["before"],
            reorderer_time_data["silent"]["after"],
            reorderer_time_data["silent"]["delta"],
        )
    )

    return table
