import unittest

from Overlay.audio_direction import (
    angular_difference,
    angle_to_sector,
    build_sector_levels,
    direction_angle_from_balance,
    smooth_angle,
)


class AudioDirectionTests(unittest.TestCase):
    def test_cardinal_sector_mapping(self):
        self.assertEqual(angle_to_sector(0), 0)
        self.assertEqual(angle_to_sector(90), 4)
        self.assertEqual(angle_to_sector(180), 8)
        self.assertEqual(angle_to_sector(270), 12)

    def test_front_balance_mapping(self):
        self.assertEqual(angle_to_sector(direction_angle_from_balance(0.0, is_back=False)), 0)
        self.assertEqual(angle_to_sector(direction_angle_from_balance(1.0, is_back=False)), 4)
        self.assertEqual(angle_to_sector(direction_angle_from_balance(-1.0, is_back=False)), 12)

    def test_back_balance_mapping_keeps_left_and_right_correct(self):
        self.assertEqual(angle_to_sector(direction_angle_from_balance(0.0, is_back=True)), 8)
        self.assertEqual(angle_to_sector(direction_angle_from_balance(1.0, is_back=True)), 4)
        self.assertEqual(angle_to_sector(direction_angle_from_balance(-1.0, is_back=True)), 12)

    def test_swap_channels_inverts_left_right(self):
        normal = angle_to_sector(direction_angle_from_balance(1.0, is_back=False))
        swapped = angle_to_sector(direction_angle_from_balance(1.0, is_back=False, swap_channels=True))
        self.assertEqual(normal, 4)
        self.assertEqual(swapped, 12)

    def test_sector_levels_have_center_and_falloff(self):
        sectors = build_sector_levels(90, 1.0, spread=2)
        self.assertEqual(sectors[4], 1.0)
        self.assertEqual(sectors[3], 0.5)
        self.assertEqual(sectors[5], 0.5)
        self.assertEqual(sectors[2], 0.25)
        self.assertEqual(sectors[6], 0.25)

    def test_angular_difference_wraps_short_way(self):
        self.assertEqual(angular_difference(10, 350), 20)
        self.assertEqual(angular_difference(350, 10), -20)

    def test_smooth_angle_crosses_zero_without_spinning(self):
        self.assertEqual(round(smooth_angle(350, 10, 0.5)), 0)
        self.assertEqual(round(smooth_angle(10, 350, 0.5)), 0)


if __name__ == "__main__":
    unittest.main()

