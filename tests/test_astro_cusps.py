import importlib.machinery
import sys
import unittest
from types import ModuleType

if "swisseph" not in sys.modules:
    try:
        import swisseph  # noqa: F401
    except ModuleNotFoundError:
        _swe = ModuleType("swisseph")
        _swe.__spec__ = importlib.machinery.ModuleSpec("swisseph", loader=None)
        for _name, _code in (
            ("SUN", 0), ("MOON", 1), ("MERCURY", 2), ("VENUS", 3), ("MARS", 4),
            ("JUPITER", 5), ("SATURN", 6), ("URANUS", 7), ("NEPTUNE", 8), ("PLUTO", 9),
        ):
            setattr(_swe, _name, _code)
        sys.modules["swisseph"] = _swe

from services.astro import SIGNS, _ascendant_and_house_cusps, chart_matches_profile


class AscendantCuspTests(unittest.TestCase):
    def test_unused_leading_zero_is_not_aries(self):
        # C-style binding: cusps[0] is empty, house 1 is cusps[1] == ascmc[0].
        cusps = (0.0, 125.4, 150.0, 180.0, 210.0, 240.0, 270.0, 305.4, 330.0, 5.4, 35.4, 65.4, 95.4)
        angles = (125.4, 5.4, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ascendant, houses = _ascendant_and_house_cusps(cusps, angles)
        self.assertEqual(ascendant, 125.4)
        self.assertEqual(SIGNS[int(ascendant // 30)], "Лев")
        self.assertEqual(len(houses), 12)
        self.assertEqual(houses[0], 125.4)
        self.assertNotEqual(houses[0], 0.0)

    def test_twelve_cusps_keep_house_one_as_ascendant(self):
        cusps = tuple(index * 30.0 for index in range(12))
        angles = (0.0, 270.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ascendant, houses = _ascendant_and_house_cusps(cusps, angles)
        self.assertEqual(ascendant, 0.0)
        self.assertEqual(houses[0], 0.0)
        self.assertEqual(houses[1], 30.0)
        self.assertEqual(len(houses), 12)

    def test_shifted_cusps_rotate_until_house_one_matches_ascendant(self):
        cusps = (200.0, 230.0, 15.5, 45.0, 75.0, 105.0, 135.0, 165.0, 195.0, 225.0, 255.0, 285.0)
        angles = (15.5, 105.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        ascendant, houses = _ascendant_and_house_cusps(cusps, angles)
        self.assertEqual(ascendant, 15.5)
        self.assertEqual(houses[0], 15.5)
        self.assertEqual(SIGNS[int(ascendant // 30)], "Овен")
        self.assertEqual(houses[1], 45.0)

    def test_profile_date_change_does_not_match_old_chart(self):
        chart = {
            "date": "1990-03-21",
            "time": "14:30",
            "time_is_approximate": False,
            "latitude": 55.75,
            "longitude": 37.62,
        }
        profile = {
            "birth_date": "1991-03-21",
            "birth_time": "14:30",
            "time_is_approximate": 0,
            "latitude": 55.75,
            "longitude": 37.62,
        }
        self.assertFalse(chart_matches_profile(chart, profile))
        profile["birth_date"] = "1990-03-21"
        self.assertTrue(chart_matches_profile(chart, profile))
