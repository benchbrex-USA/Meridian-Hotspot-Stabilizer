import unittest

from meridian_stabilizer.service import build_launchd_plist, build_notifier_launchd_plist


class ServiceTests(unittest.TestCase):
    def test_service_plist_supervises_unsuccessful_exit(self):
        plist = build_launchd_plist(profile="calls", interval=60, guardian=True)

        self.assertEqual(plist["KeepAlive"], {"SuccessfulExit": False})
        self.assertEqual(plist["RunAtLoad"], True)
        self.assertEqual(plist["ThrottleInterval"], 30)
        self.assertNotIn("PYTHONPATH", plist["EnvironmentVariables"])
        self.assertEqual(plist["EnvironmentVariables"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(plist["WorkingDirectory"], "/Users/Shared/meridian-hotspot-stabilizer/runtime")
        self.assertIn("--guardian", plist["ProgramArguments"])
        self.assertIn("/Users/Shared/meridian-hotspot-stabilizer/runtime", plist["ProgramArguments"][2])

    def test_service_plist_can_be_installed_without_starting(self):
        plist = build_launchd_plist(profile="calls", interval=60, guardian=True, start_immediately=False)

        self.assertEqual(plist["RunAtLoad"], False)
        self.assertEqual(plist["KeepAlive"], False)

    def test_notifier_plist_runs_user_bridge(self):
        plist = build_notifier_launchd_plist(interval=5)

        self.assertIn("notify-drain", plist["ProgramArguments"])
        self.assertIn("--watch", plist["ProgramArguments"])
        self.assertNotIn("PYTHONPATH", plist["EnvironmentVariables"])
        self.assertEqual(plist["EnvironmentVariables"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(plist["WorkingDirectory"], "/Users/Shared/meridian-hotspot-stabilizer/runtime")
        self.assertIn("/Users/Shared/meridian-hotspot-stabilizer/runtime", plist["ProgramArguments"][2])
        self.assertEqual(plist["ProcessType"], "Background")


if __name__ == "__main__":
    unittest.main()
