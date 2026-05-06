import tempfile
import unittest
from pathlib import Path

from meridian_stabilizer.database import MetricsDB
from meridian_stabilizer.parsers import NetworkQuality, PingStats, RouteInfo
from meridian_stabilizer.state import StabilizerState


class DatabaseTests(unittest.TestCase):
    def test_records_events_and_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MetricsDB(Path(tmp) / "metrics.sqlite3")
            event = db.record_event("test", "real event", {"ok": True})
            self.assertEqual(event.kind, "test")

            state = StabilizerState(active=True, profile="calls", upload_cap_mbps=8.0, download_cap_mbps=25.0)
            route = RouteInfo(interface="en0", gateway="10.0.0.1")
            gateway_ping = PingStats(4, 4, 0.0, 2.0, 3.0, 4.0, 0.5)
            internet_ping = PingStats(4, 4, 0.0, 50.0, 60.0, 80.0, 8.0)
            quality = NetworkQuality(upload_mbps=20.0, download_mbps=100.0, upload_responsiveness="Medium")
            sample = db.record_sample(state, route, gateway_ping, internet_ping, quality)

            self.assertEqual(sample.interface, "en0")
            self.assertEqual(sample.stability_label, "Excellent")
            self.assertEqual(len(db.recent_events()), 1)
            self.assertEqual(len(db.recent_samples()), 1)
            self.assertIsNotNone(db.latest_sample())


if __name__ == "__main__":
    unittest.main()

