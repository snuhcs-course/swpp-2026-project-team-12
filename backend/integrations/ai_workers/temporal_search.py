"""Resolve the question's date and favor recent evidence within the relevance ranking."""

import re
from datetime import UTC, date, datetime, time, timedelta

from django.utils import timezone
from graphiti_core.search.search_filters import ComparisonOperator, DateFilter, SearchFilters


DAY = timedelta(days=1)
DATE_EXPRESSION = re.compile(
    r"(?<!\d)(?:(\d{4})년\s*|(작년|지난해|올해|내년)\s*)?(\d{1,2})월\s*(\d{1,2})일"
    r"|(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"
    r"|(?<![가-힣])(그저께|그제|어제|오늘)(?=$|[^가-힣\d]|에|는|도|쯤|부터|까지)"
)
RELATIVE_DAYS = {"그저께": -2, "그제": -2, "어제": -1, "오늘": 0}
RELATIVE_YEARS = {"작년": -1, "지난해": -1, "올해": 0, "내년": 1}
APPROXIMATE = re.compile(r"\s*(?:쯤|경(?![가-힣])|무렵|전후)")
RANGE_SUFFIX = re.compile(r"\s*(?:부터|까지|이전|이후|[-~–])")
SCHEDULE = re.compile(r"예정|계획|약속|하기로|만나기로|가기로")
CURRENT = re.compile(r"(?<![가-힣])(?:지금(?!까지)|현재(?!까지))")


def date_window(question, reference_time):
    """Resolve a single event day. A scheduled date can differ from a fact's valid_at."""
    if SCHEDULE.search(question):
        return None
    matches = list(DATE_EXPRESSION.finditer(question))
    if len(matches) != 1:
        return None
    match, = matches
    if RANGE_SUFFIX.match(question, match.end()):
        return None
    year, relative_year, month, day, iso_year, iso_month, iso_day, relative = match.groups()
    local_reference = timezone.localtime(reference_time)
    offset = RELATIVE_DAYS.get(relative)
    try:
        if offset is not None:
            asked_day = local_reference.date() + offset * DAY
        else:
            local_year = local_reference.year + RELATIVE_YEARS.get(relative_year, 0)
            asked_day = date(int(year or iso_year or local_year), int(month or iso_month), int(day or iso_day))
        day_start = datetime.combine(asked_day, time.min, local_reference.tzinfo)
        if APPROXIMATE.match(question, match.end()):
            start, end = day_start - DAY, day_start + 2 * DAY
        else:
            start, end = day_start, day_start + DAY
        return start.astimezone(UTC), end.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def fact_time_filter(question, window, reference_time):
    if window is not None:
        start, end = window
        return SearchFilters(valid_at=[[
            DateFilter(date=start, comparison_operator=ComparisonOperator.greater_than_equal),
            DateFilter(date=end, comparison_operator=ComparisonOperator.less_than),
        ]])
    if CURRENT.search(question) and not SCHEDULE.search(question):
        reference_time = reference_time.astimezone(UTC)
        return SearchFilters(
            valid_at=[[DateFilter(date=reference_time, comparison_operator=ComparisonOperator.less_than_equal)],
                      [DateFilter(comparison_operator=ComparisonOperator.is_null)]],
            invalid_at=[[DateFilter(date=reference_time, comparison_operator=ComparisonOperator.greater_than)],
                        [DateFilter(comparison_operator=ComparisonOperator.is_null)]],
        )
    return None


def time_rank(score, timestamp, reference_time, window):
    """Put the center day first for approximate dates and favor recent undated matches."""
    if window is not None:
        start, end = window
        on_requested_day = timestamp is not None and start + DAY <= timestamp < end - DAY
        return on_requested_day, score
    if timestamp is None or timestamp > reference_time:
        return False, score
    age_in_fortnights = (reference_time - timestamp) / (14 * DAY)
    return False, score + 0.12 * 2 ** -age_in_fortnights
