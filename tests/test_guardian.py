import tempfile
import unittest
from pathlib import Path

from meridian_stabilizer.guardian import GuardianPolicy, evaluate_guardian, write_incident_report
from meridian_stabilizer.measurements import RuntimeSnapshot
from meridian_stabilizer.parsers import PingStats, RouteInfo
from meridian_stabilizer.state import StabilizerState


class GuardianTests(unittest.TestCase):
    def test_continue_on_healthy_link(self):
        snapshot = RuntimeSnapshot(
            route=RouteInfo(interface="en0", gateway="10.0.0.1"),
            gateway_ping=PingStats(4, 4, 0.0, 3.0, 4.0, 5.0, 0.5),
            internet_ping=PingStats(4, 4, 0.0, 40.0, 60.0, 80.0, 8.0),
            quality=None,
        )
        decision = evaluate_guardian(snapshot, StabilizerState(active=True), GuardianPolicy())
        self.assertEqual(decision.action, "continue")

    def test_shutdown_on_high_loss(self):
        snapshot = RuntimeSnapshot(
            route=RouteInfo(interface="en0", gateway="10.0.0.1"),
            gateway_ping=PingStats(4, 4, 0.0, 3.0, 4.0, 5.0, 0.5),
            internet_ping=PingStats(4, 2, 50.0, 40.0, 60.0, 80.0, 8.0),
            quality=None,
        )
        decision = evaluate_guardian(snapshot, StabilizerState(active=True), GuardianPolicy(max_loss_percent=5.0))
        self.assertEqual(decision.action, "shutdown")
        self.assertIn("packet loss", decision.reason)

    def test_writes_incident_report(self):
        snapshot = RuntimeSnapshot(route=None, gateway_ping=None, internet_ping=None, quality=None, errors=("default route unavailable",))
        decision = evaluate_guardian(snapshot, StabilizerState(active=True), GuardianPolicy(max_consecutive_probe_failures=1), consecutive_failures=1)
        with tempfile.TemporaryDirectory() as tmp:
            md_path, json_path = write_incident_report(Path(tmp), decision, snapshot, StabilizerState(active=True))
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("Resolution Plan", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

