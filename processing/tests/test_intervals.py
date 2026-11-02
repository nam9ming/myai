from datetime import datetime
import unittest

from processing.matching.intervals import union, intersect, subtract, business_hours, occurrence_intervals, KST


def at(day, hour=0, minute=0, second=0):
    return datetime(2026, 11, day, hour, minute, second, tzinfo=KST)


def hours(state='closed'):
    return {d: dict(state=state, full_day=False, intervals=[]) for d in
            ('monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday')}


def occurrence(**changes):
    return dict(date_start='2026-11-03', date_end='2026-11-03', time_start='10:00',
                time_end='12:00', end_day_offset=0, precision='exact_time', recurrence_dates=None) | changes


class IntervalTest(unittest.TestCase):
    def test_half_open_union_and_intersection(self):
        self.assertEqual([(at(3, 9), at(3, 18))], union([(at(3, 9), at(3, 12)), (at(3, 12), at(3, 18)), (at(3, 10), at(3, 11))]))
        self.assertEqual([], intersect([(at(3, 9), at(3, 12))], [(at(3, 12), at(3, 18))]))

    def test_subtract_known_portions_from_unknown(self):
        self.assertEqual([(at(3, 9), at(3, 10)), (at(3, 12), at(3, 18))],
                         subtract([(at(3, 9), at(3, 18))], [(at(3, 10), at(3, 12))]))

    def test_previous_overnight_survives_closed_anchor_day(self):
        h = hours()
        h['monday'] = dict(state='open', full_day=False, intervals=[dict(start='22:00', end='02:00', end_day_offset=1)])
        known, unknown = business_hours(h, at(3), at(17))
        self.assertIn((at(3), at(3, 2)), known)
        self.assertEqual([], unknown)

    def test_unknown_previous_day_can_carry_into_closed_day(self):
        h = hours()
        h['monday']['state'] = 'unknown'
        known, unknown = business_hours(h, at(3), at(17))
        self.assertEqual([], known)
        self.assertIn((at(3), at(4)), unknown)

    def test_full_day_covers_previous_unknown(self):
        h = hours('open')
        for day in h.values():
            day['full_day'] = True
        h['monday'] = dict(state='unknown', full_day=False, intervals=[])
        known, unknown = business_hours(h, at(3), at(4))
        self.assertEqual([(at(3), at(4))], known)
        self.assertEqual([], unknown)

    def test_continuous_exact_interval_and_explicit_recurrence(self):
        occ = occurrence(date_end='2026-11-05')
        exact, intervals = occurrence_intervals(occ, at(3), at(17))
        self.assertTrue(exact)
        self.assertEqual([(at(3, 10), at(5, 12))], intervals)
        occ['recurrence_dates'] = ['2026-11-03', '2026-11-05']
        self.assertEqual([(at(3, 10), at(3, 12)), (at(5, 10), at(5, 12))], occurrence_intervals(occ, at(3), at(17))[1])

    def test_empty_recurrence_means_no_occurrences(self):
        self.assertEqual((True, []), occurrence_intervals(occurrence(recurrence_dates=[]), at(3), at(17)))

    def test_date_only_is_unknown_and_inclusive(self):
        occ = occurrence(date_end='2026-11-05', precision='date_only', time_start=None, time_end=None, end_day_offset=None)
        self.assertEqual((False, [(at(3), at(6))]), occurrence_intervals(occ, at(3), at(17)))

    def test_partial_unknown_date_can_be_excluded(self):
        occ = occurrence(date_start=None, date_end='2026-11-01', precision='unknown', time_start=None, time_end=None, end_day_offset=None)
        self.assertEqual((False, []), occurrence_intervals(occ, at(3), at(17)))

    def test_window_excludes_14th_midnight_and_preserves_seconds(self):
        self.assertEqual((True, []), occurrence_intervals(occurrence(date_start='2026-11-17', date_end='2026-11-17'), at(3), at(17)))
        self.assertEqual([(at(3, 10, 0, 1), at(3, 10, 0, 2))], occurrence_intervals(occurrence(time_start='10:00:01', time_end='10:00:02'), at(3), at(17))[1])

    def test_explicit_overnight_end_date_is_not_advanced_twice(self):
        occ = occurrence(date_start='2026-11-02', date_end='2026-11-03', time_start='22:00', time_end='02:00', end_day_offset=1)
        self.assertEqual([(at(3), at(3, 2))], occurrence_intervals(occ, at(3), at(17))[1])

    def test_partial_unknown_preserves_known_datetime_boundaries(self):
        occ = occurrence(date_start='2026-11-16', date_end=None, time_start='20:00', time_end=None,
                         end_day_offset=None, precision='unknown')
        self.assertEqual((False, [(at(16, 20), at(17))]), occurrence_intervals(occ, at(3), at(17)))
        occ.update(date_start=None, date_end='2026-11-03', time_start=None, time_end='02:00', end_day_offset=0)
        self.assertEqual((False, [(at(3), at(3, 2))]), occurrence_intervals(occ, at(3), at(17)))
