import argparse
import io
import unittest
from contextlib import redirect_stdout

from meridian_stabilizer.cli import build_parser, cmd_install, _post_apply_safety_failure
from meridian_stabilizer.measurements import RuntimeSnapshot
from meridian_stabilizer.parsers import PingStats, RouteInfo


class CliTests(unittest.TestCase):
    def test_install_command_defaults_to_production_setup(self):
        args = build_parser().parse_args(["install", "--dry-run", "--skip-preflight"])

        self.assertEqual(args.profile, "calls")
        self.assertEqual(args.interval, 60)
        self.assertTrue(args.guardian)
        self.assertTrue(args.notifier)
        self.assertFalse(args.start_now)
        self.assertTrue(args.dry_run)

    def test_install_dry_run_combines_service_and_notifier(self):
        args = argparse.Namespace(profile="calls", interval=60, guardian=True, notifier=True, start_now=False, skip_preflight=True, dry_run=True)
        output = io.StringIO()

        with redirect_stdout(output):
            result = cmd_install(args)

        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("safe install", text)
        self.assertIn("com.meridian.hotspot-stabilizer.plist", text)
        self.assertIn("com.meridian.hotspot-stabilizer.notify.plist", text)
        self.assertIn("launchctl disable system/com.meridian.hotspot-stabilizer", text)
        self.assertNotIn("launchctl bootstrap system /Library/LaunchDaemons/com.meridian.hotspot-stabilizer.plist", text)
        self.assertNotIn("kickstart", text)

    def test_post_apply_safety_detects_failed_internet_probe(self):
        snapshot = RuntimeSnapshot(
            route=RouteInfo(interface="en0", gateway="10.0.0.1"),
            gateway_ping=None,
            internet_ping=PingStats(transmitted=3, received=0, loss_percent=100.0, min_ms=None, avg_ms=None, max_ms=None, stddev_ms=None),
            quality=None,
        )

        self.assertIn("no replies", _post_apply_safety_failure(snapshot))

    def test_post_apply_safety_allows_healthy_probe(self):
        snapshot = RuntimeSnapshot(
            route=RouteInfo(interface="en0", gateway="10.0.0.1"),
            gateway_ping=None,
            internet_ping=PingStats(transmitted=3, received=3, loss_percent=0.0, min_ms=20.0, avg_ms=25.0, max_ms=30.0, stddev_ms=2.0),
            quality=None,
        )

        self.assertIsNone(_post_apply_safety_failure(snapshot))


if __name__ == "__main__":
    unittest.main()
