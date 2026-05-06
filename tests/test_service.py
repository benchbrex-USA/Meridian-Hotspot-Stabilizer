import unittest

from meridian_stabilizer.service import build_launchd_plist, build_notifier_launchd_plist


class ServiceTests(unittest.TestCase):
    def test_service_plist_supervises_unsuccessful_exit(self):
        plist = build_launchd_plist(profile="calls", interval=60, guardian=True)

        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(plist["ThrottleInterval"], 30)
        self.assertIn("--guardian", plist["ProgramArguments"])

    def test_notifier_plist_runs_user_bridge(self):
        plist = build_notifier_launchd_plist(interval=5)

        self.assertIn("notify-drain", plist["ProgramArguments"])
        self.assertIn("--watch", plist["ProgramArguments"])
        self.assertEqual(plist["ProcessType"], "Background")


if __name__ == "__main__":
    unittest.main()
