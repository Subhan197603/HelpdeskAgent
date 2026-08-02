"""Deterministic business-time arithmetic with IANA timezone and DST handling."""

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.api.app.sla.models import (
    BusinessCalendarVersion,
    CalendarException,
    CalendarExceptionType,
    WorkingPeriod,
)


class CalendarConfigurationError(ValueError):
    """Raised when a published calendar cannot be evaluated deterministically."""


class BusinessCalendar:
    """Evaluate one immutable calendar version in absolute UTC time."""

    _MAX_SEARCH_DAYS = 3660

    def __init__(self, version: BusinessCalendarVersion) -> None:
        self.version = version
        try:
            self._timezone = ZoneInfo(version.timezone_name)
        except ZoneInfoNotFoundError as error:
            raise CalendarConfigurationError("Business calendar timezone is unknown.") from error
        self._periods = self._validated_periods(version.working_periods)
        self._exceptions = self._validated_exceptions()

    def add_business_seconds(self, start: datetime, seconds: int) -> datetime:
        """Return the UTC instant reached after consuming business seconds."""
        current = _utc(start)
        if seconds < 0:
            raise ValueError("Business seconds cannot be negative.")
        if seconds == 0:
            return current
        remaining = seconds
        local_date = current.astimezone(self._timezone).date()
        for day_offset in range(self._MAX_SEARCH_DAYS):
            for interval_start, interval_end in self._intervals(local_date + timedelta(day_offset)):
                cursor = max(current, interval_start)
                if cursor >= interval_end:
                    continue
                available = int((interval_end - cursor).total_seconds())
                if remaining <= available:
                    return cursor + timedelta(seconds=remaining)
                remaining -= available
            current = self._local_boundary(
                datetime.combine(local_date + timedelta(day_offset + 1), time.min),
                end=False,
            )
        raise CalendarConfigurationError("Business-time calculation exceeds ten years.")

    def business_seconds_between(self, start: datetime, end: datetime) -> int:
        """Count calendar-open seconds in the half-open interval [start, end)."""
        lower = _utc(start)
        upper = _utc(end)
        if upper <= lower:
            return 0
        first = lower.astimezone(self._timezone).date()
        last = upper.astimezone(self._timezone).date()
        total = 0
        day = first
        while day <= last:
            for interval_start, interval_end in self._intervals(day):
                overlap_start = max(lower, interval_start)
                overlap_end = min(upper, interval_end)
                if overlap_end > overlap_start:
                    total += int((overlap_end - overlap_start).total_seconds())
            day += timedelta(days=1)
        return total

    def _intervals(self, local_date: date) -> tuple[tuple[datetime, datetime], ...]:
        if self.version.twenty_four_seven:
            return (
                (
                    self._local_boundary(datetime.combine(local_date, time.min), end=False),
                    self._local_boundary(
                        datetime.combine(local_date + timedelta(days=1), time.min), end=True
                    ),
                ),
            )

        exceptions = self._exceptions.get(local_date, ())
        if any(item.exception_type is CalendarExceptionType.CLOSED for item in exceptions):
            return ()
        custom = [
            WorkingPeriod(
                local_date.isoweekday(),
                item.start_local_time or time.min,
                item.end_local_time or time.min,
            )
            for item in exceptions
            if item.exception_type is CalendarExceptionType.CUSTOM_HOURS
        ]
        periods = custom or list(self._periods.get(local_date.isoweekday(), ()))
        intervals = [
            (
                self._local_boundary(
                    datetime.combine(local_date, period.start_local_time), end=False
                ),
                self._local_boundary(datetime.combine(local_date, period.end_local_time), end=True),
            )
            for period in periods
        ]
        return _merge_intervals(intervals)

    def _local_boundary(self, naive: datetime, *, end: bool) -> datetime:
        candidates: list[datetime] = []
        for fold in (0, 1):
            aware = naive.replace(tzinfo=self._timezone, fold=fold)
            utc_value = aware.astimezone(UTC)
            if utc_value.astimezone(self._timezone).replace(tzinfo=None) == naive:
                candidates.append(utc_value)
        if candidates:
            return (max if end else min)(candidates)
        # Map a boundary inside a spring-forward gap to the first valid instant
        # after the gap so a published schedule remains total and deterministic.
        probe = naive
        for _ in range(180):
            probe += timedelta(minutes=1)
            aware = probe.replace(tzinfo=self._timezone, fold=0)
            utc_value = aware.astimezone(UTC)
            if utc_value.astimezone(self._timezone).replace(tzinfo=None) == probe:
                return utc_value
        raise CalendarConfigurationError("Calendar contains an unresolvable local time.")

    @staticmethod
    def _validated_periods(
        periods: Iterable[WorkingPeriod],
    ) -> dict[int, tuple[WorkingPeriod, ...]]:
        result: dict[int, list[WorkingPeriod]] = {}
        for period in periods:
            if not 1 <= period.iso_day_of_week <= 7:
                raise CalendarConfigurationError("Working-period day is invalid.")
            if period.start_local_time >= period.end_local_time:
                raise CalendarConfigurationError("Working-period bounds are invalid.")
            result.setdefault(period.iso_day_of_week, []).append(period)
        normalized: dict[int, tuple[WorkingPeriod, ...]] = {}
        for day, values in result.items():
            ordered = sorted(values, key=lambda item: item.start_local_time)
            if any(
                previous.end_local_time > current.start_local_time
                for previous, current in zip(ordered, ordered[1:], strict=False)
            ):
                raise CalendarConfigurationError("Working periods overlap.")
            normalized[day] = tuple(ordered)
        return normalized

    def _validated_exceptions(self) -> dict[date, tuple[CalendarException, ...]]:
        result: dict[date, list[CalendarException]] = {}
        for exception in self.version.exceptions:
            if exception.exception_type is CalendarExceptionType.CUSTOM_HOURS and (
                exception.start_local_time is None
                or exception.end_local_time is None
                or exception.start_local_time >= exception.end_local_time
            ):
                raise CalendarConfigurationError("Custom calendar hours are invalid.")
            if exception.exception_type is CalendarExceptionType.CLOSED and (
                exception.start_local_time is not None or exception.end_local_time is not None
            ):
                raise CalendarConfigurationError("Closed calendar exceptions cannot have hours.")
            result.setdefault(exception.exception_date, []).append(exception)
        return {day: tuple(values) for day, values in result.items()}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Business-time inputs must be timezone-aware.")
    return value.astimezone(UTC)


def _merge_intervals(
    intervals: Iterable[tuple[datetime, datetime]],
) -> tuple[tuple[datetime, datetime], ...]:
    ordered = sorted((start, end) for start, end in intervals if end > start)
    merged: list[tuple[datetime, datetime]] = []
    for start, end in ordered:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return tuple(merged)
