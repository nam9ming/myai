import math
import unittest
from unittest.mock import patch

from processing.matching.geometry import EARTH_RADIUS_M, haversine, segment_distance, locate


class GeometryTest(unittest.TestCase):
    def test_haversine_zero_and_antipodes(self):
        self.assertEqual(0, haversine((127.27, 37.01), (127.27, 37.01)))
        self.assertAlmostEqual(math.pi * EARTH_RADIUS_M, haversine((0, 0), (180, 0)))
        self.assertAlmostEqual(111_195.0802335329, haversine((0, 0), (1, 0)), places=7)
        self.assertEqual(haversine((127, 37), (128, 38)), haversine((128, 38), (127, 37)))

    def test_exact_500m_raw_value_is_included(self):
        with patch('processing.matching.geometry.haversine', return_value=500.0):
            self.assertEqual((True, 500.0, 'haversine_point'), locate((0, 0), self.location([0, 0])))

    def test_500m_uses_raw_distance_without_epsilon(self):
        for metres, expected in [(499.999, True), (500.001, False)]:
            with self.subTest(metres=metres):
                lon = math.degrees(metres / EARTH_RADIUS_M)
                state, raw, basis = locate((0, 0), self.location([lon, 0]))
                self.assertIs(expected, state)
                self.assertAlmostEqual(metres, raw, places=7)
                self.assertEqual('haversine_point', basis)

    def test_independent_point_oracles(self):
        # 별도 계산한 고정값·근거: docs/superpowers/specs/2026-11-05-independent-distance-oracles-design.md
        point = (127.27, 37.01)
        for other, expected, inside in [
            ((127.27, 37.014495702498), 499.9, True),
            ((127.27, 37.014497501139), 500.1, False),
            ((127.275, 37.012), 496.5436566045, True),
        ]:
            with self.subTest(other=other):
                self.assertAlmostEqual(expected, haversine(point, other), delta=0.01)
                state, raw, basis = locate(point, self.location(list(other)))
                self.assertIs(inside, state)
                self.assertAlmostEqual(expected, raw, delta=0.01)
                self.assertEqual('haversine_point', basis)

    def test_independent_segment_oracles(self):
        for point, expected in [
            ((0, 0.004495702498), 499.9),
            ((0, 0.004497501139), 500.1),
            ((0.014495702498, 0), 499.9),
            ((0.014497501139, 0), 500.1),
        ]:
            with self.subTest(point=point):
                self.assertAlmostEqual(
                    expected, segment_distance(point, (-0.01, 0), (0.01, 0)), delta=0.01)

    def test_segment_interior_and_endpoint(self):
        self.assertAlmostEqual(0, segment_distance((0, 0), (-1, 0), (1, 0)), places=6)
        self.assertAlmostEqual(haversine((2, 0), (1, 0)), segment_distance((2, 0), (-1, 0), (1, 0)))
        self.assertAlmostEqual(haversine((0, 1), (0, 0)), segment_distance((0, 1), (-1, 0), (1, 0)), places=5)

    def test_dateline_short_arc(self):
        self.assertAlmostEqual(0, segment_distance((180, 0), (179, 0), (-179, 0)), places=6)
        self.assertGreater(segment_distance((0, 0), (179, 0), (-179, 0)), 10_000_000)

    def test_identical_and_antipodal_endpoints(self):
        self.assertEqual(haversine((1, 0), (0, 0)), segment_distance((1, 0), (0, 0), (0, 0)))
        with self.assertRaises(ValueError):
            segment_distance((0, 1), (0, 0), (180, 0))

    def test_polar_projection_degeneracy_uses_endpoints(self):
        self.assertAlmostEqual(math.pi * EARTH_RADIUS_M / 2, segment_distance((0, 90), (-10, 0), (10, 0)))

    def test_partial_inside_true_outside_unknown(self):
        inside = self.location([0, 0], coverage='partial')
        outside = self.location([1, 0], coverage='partial')
        self.assertIs(True, locate((0, 0), inside)[0])
        self.assertIsNone(locate((0, 0), outside)[0])
        self.assertIsNone(locate((0, 0), outside)[1])

    def test_area_and_unverified_coordinates_do_not_make_distance(self):
        for changes in [{'kind': 'area'}, {'status': 'ambiguous'}, {'coverage': 'unknown'}]:
            self.assertEqual((None, None, None), locate((0, 0), self.location([0, 0], **changes)))

    def test_stops_and_polyline_take_minimum(self):
        loc = self.location([0, 0])
        loc.update(kind='stops', geometry={'type': 'MultiPoint', 'coordinates': [[1, 0], [0, 0]]})
        self.assertEqual((True, 0, 'minimum_verified_stops'), locate((0, 0), loc))
        loc.update(kind='segment', geometry={'type': 'LineString', 'coordinates': [[-1, 1], [-1, 0], [1, 0]]})
        state, raw, basis = locate((0, 0), loc)
        self.assertIs(True, state)
        self.assertAlmostEqual(0, raw, places=6)
        self.assertEqual('great_circle_segment', basis)

    @staticmethod
    def location(coordinates, **changes):
        return dict(kind='point', status='verified', coverage='complete',
                    geometry={'type': 'Point', 'coordinates': coordinates}) | changes
