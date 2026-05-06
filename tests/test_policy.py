import unittest

from meridian_stabilizer.parsers import NetworkQuality, PingStats
from meridian_stabilizer.policy import CALLS_PROFILE, get_profile, initial_caps, profile_names, tune_caps
from meridian_stabilizer.state import StabilizerState


class PolicyTests(unittest.TestCase):
    def test_initial_caps_use_calls_headroom(self):
        caps = initial_caps(NetworkQuality(upload_mbps=44.514, download_mbps=354.382), CALLS_PROFILE)
        self.assertEqual(caps.upload_mbps, 35.611)
        self.assertEqual(caps.download_mbps, 301.225)

    def test_initial_caps_without_measurement_avoid_low_download_fallback(self):
        caps = initial_caps(None, CALLS_PROFILE)

        self.assertEqual(caps.upload_mbps, 12.0)
        self.assertEqual(caps.download_mbps, 250.0)

    def test_profiles_include_production_modes(self):
        self.assertEqual(profile_names(), ["auto", "calls", "downloads", "gaming"])
        self.assertEqual(get_profile("gaming").description.startswith("Favor"), True)

    def test_tune_reduces_on_spiky_latency(self):
        state = StabilizerState(upload_cap_mbps=35.0, download_cap_mbps=300.0, measured_upload_mbps=44.0, measured_download_mbps=350.0)
        ping = PingStats(transmitted=8, received=8, loss_percent=0.0, min_ms=42.0, avg_ms=190.0, max_ms=360.0, stddev_ms=95.0)
        decision = tune_caps(state, ping, quality=None)
        self.assertEqual(decision.action, "reduced")
        self.assertLess(decision.caps.upload_mbps, 35.0)
        self.assertLess(decision.caps.download_mbps, 300.0)

    def test_tune_raises_slowly_when_stable(self):
        state = StabilizerState(upload_cap_mbps=20.0, download_cap_mbps=100.0, measured_upload_mbps=44.0, measured_download_mbps=350.0)
        ping = PingStats(transmitted=8, received=8, loss_percent=0.0, min_ms=40.0, avg_ms=70.0, max_ms=95.0, stddev_ms=12.0)
        decision = tune_caps(state, ping, quality=None)
        self.assertEqual(decision.action, "increased")
        self.assertEqual(decision.caps.upload_mbps, 21.0)
        self.assertEqual(decision.caps.download_mbps, 103.0)

    def test_tune_holds_at_measured_limit(self):
        state = StabilizerState(upload_cap_mbps=35.2, download_cap_mbps=297.5, measured_upload_mbps=44.0, measured_download_mbps=350.0)
        ping = PingStats(transmitted=8, received=8, loss_percent=0.0, min_ms=40.0, avg_ms=70.0, max_ms=95.0, stddev_ms=12.0)
        decision = tune_caps(state, ping, quality=None)
        self.assertEqual(decision.action, "held")


if __name__ == "__main__":
    unittest.main()
