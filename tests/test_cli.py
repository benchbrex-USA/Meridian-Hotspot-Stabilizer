import argparse
import io
import unittest
from contextlib import redirect_stdout

from meridian_stabilizer.cli import build_parser, cmd_install


class CliTests(unittest.TestCase):
    def test_install_command_defaults_to_production_setup(self):
        args = build_parser().parse_args(["install", "--dry-run", "--skip-preflight"])

        self.assertEqual(args.profile, "calls")
        self.assertEqual(args.interval, 60)
        self.assertTrue(args.guardian)
        self.assertTrue(args.notifier)
        self.assertTrue(args.dry_run)

    def test_install_dry_run_combines_service_and_notifier(self):
        args = argparse.Namespace(profile="calls", interval=60, guardian=True, notifier=True, skip_preflight=True, dry_run=True)
        output = io.StringIO()

        with redirect_stdout(output):
            result = cmd_install(args)

        self.assertEqual(result, 0)
        text = output.getvalue()
        self.assertIn("one-command install", text)
        self.assertIn("com.meridian.hotspot-stabilizer.plist", text)
        self.assertIn("com.meridian.hotspot-stabilizer.notify.plist", text)


if __name__ == "__main__":
    unittest.main()
