import unittest

from Overlay.audio_events import classify_audio_event


class AudioEventTests(unittest.TestCase):
    def test_idle_below_noise_floor(self):
        self.assertEqual(classify_audio_event(0.01, 0.0, 1000, 0.02), "IDLE")

    def test_impact_for_loud_attack(self):
        self.assertEqual(classify_audio_event(0.9, 0.4, 1800, 0.02), "IMPACT")

    def test_step_for_mid_band_attack(self):
        self.assertEqual(classify_audio_event(0.28, 0.12, 900, 0.02), "STEP")

    def test_movement_suppresses_step_label(self):
        self.assertNotEqual(classify_audio_event(0.28, 0.12, 900, 0.02, is_moving=True), "STEP")

    def test_sharp_high_frequency_event(self):
        self.assertEqual(classify_audio_event(0.35, 0.32, 3500, 0.02), "SHARP")

    def test_low_frequency_event(self):
        self.assertEqual(classify_audio_event(0.12, 0.1, 180, 0.02), "LOW")


if __name__ == "__main__":
    unittest.main()

