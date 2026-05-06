import unittest

from meridian_stabilizer.health import score_link
from meridian_stabilizer.parsers import NetworkQuality, PingStats


class HealthTests(unittest.TestCase):
    def test_score_unavailable_without_ping(self):
        score = score_link(None)
        self.assertIsNone(score.score)
        self.assertEqual(score.label, "Unavailable")

    def test_score_penalizes_loss_and_jitter(self):
        ping = PingStats(transmitted=8, received=7, loss_percent=12.5, min_ms=40.0, avg_ms=210.0, max_ms=520.0, stddev_ms=130.0)
        score = score_link(ping, NetworkQuality(upload_responsiveness="Low"))
        self.assertLess(score.score, 50)
        self.assertEqual(score.label, "Poor")

    def test_score_excellent_for_stable_link(self):
        ping = PingStats(transmitted=8, received=8, loss_percent=0.0, min_ms=40.0, avg_ms=55.0, max_ms=70.0, stddev_ms=5.0)
        score = score_link(ping)
        self.assertEqual(score.score, 100)
        self.assertEqual(score.label, "Excellent")


if __name__ == "__main__":
    unittest.main()

