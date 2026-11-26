"""Resolve the question's date and favor recent evidence within the relevance ranking."""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from django.utils import timezone
from graphiti_core.search.search_filters import ComparisonOperator, DateFilter, SearchFilters


DAY = timedelta(days=1)
DATE_EXPRESSION = re.compile(
    r"(?<!\d)(?:(\d{4})년\s*|(작년|지난해|올해|내년)\s*)?(\d{1,2})월\s*(\d{1,2})일"
    r"|(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"
    r"|(?<![가-힣])(그저께|그제|어제|오늘)(?=$|[^가-힣\d]|에|는|도|쯤|부터|까지|기준)"
)
RELATIVE_DAYS = {"그저께": -2, "그제": -2, "어제": -1, "오늘": 0}
RELATIVE_YEARS = {"작년": -1, "지난해": -1, "올해": 0, "내년": 1}
RANGE_SUFFIX = re.compile(r"\s*(?:부터|까지|이전|이후|[-~–])")
AS_OF_SUFFIX = re.compile(r"\s*(?:(?:을|를)\s*)?기준")
SCHEDULE = re.compile(r"예정|계획|약속|하기로|만나기로|가기로")
CURRENT = re.compile(r"(?<![가-힣])(?:지금(?!까지)|현재(?!까지))")


@dataclass(frozen=True)
class DatePreference:
    day: date
    cutoff: datetime | None = None


def date_preference(question, reference_time):
    """Resolve a date for ranking, with a knowledge cutoff for an explicit 'as of'."""
    matches = list(DATE_EXPRESSION.finditer(question or ""))
    as_of = [match for match in matches if AS_OF_SUFFIX.match(question, match.end())]
    if len(as_of) == 1:
        match, = as_of
    elif len(matches) == 1 and not RANGE_SUFFIX.match(question, matches[0].end()):
        match, = matches
    else:
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
        cutoff = None
        if as_of:
            next_day = datetime.combine(asked_day + DAY, time.min, local_reference.tzinfo)
            cutoff = min(reference_time, next_day.astimezone(UTC) - timedelta(microseconds=1))
        return DatePreference(asked_day, cutoff)
    except (ValueError, OverflowError):
        return None


def fact_time_filter(question, preference, reference_time):
    if CURRENT.search(question) and not SCHEDULE.search(question) and (preference is None or preference.cutoff):
        reference_time = (preference.cutoff if preference else reference_time).astimezone(UTC)
        return SearchFilters(
            valid_at=[[DateFilter(date=reference_time, comparison_operator=ComparisonOperator.less_than_equal)],
                      [DateFilter(comparison_operator=ComparisonOperator.is_null)]],
            invalid_at=[[DateFilter(date=reference_time, comparison_operator=ComparisonOperator.greater_than)],
                        [DateFilter(comparison_operator=ComparisonOperator.is_null)]],
        )
    return None


def time_rank(score, timestamp, reference_time, preference):
    """Boost nearby dates without removing stronger matches from other days."""
    if timestamp is None:
        return score
    if preference is not None:
        distance = abs((timezone.localtime(timestamp).date() - preference.day).days)
        return score + 0.20 * 2 ** -(distance / 3)
    if timestamp > reference_time:
        return score
    age_in_fortnights = (reference_time - timestamp) / (14 * DAY)
    return score + 0.12 * 2 ** -age_in_fortnights
