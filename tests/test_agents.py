import tempfile
import unittest
from pathlib import Path

from meridian_stabilizer.agents import build_agent_context, detect_providers, render_agent_context_markdown
from meridian_stabilizer.database import MetricsDB
from meridian_stabilizer.state import StabilizerState


class AgentTests(unittest.TestCase):
    def test_detect_known_provider_without_login(self):
        providers = detect_providers("codex")
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0].name, "codex")
        self.assertIn("user-managed", providers[0].auth_model)

    def test_build_context_without_live_measurements(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MetricsDB(Path(tmp) / "metrics.sqlite3")
            state = StabilizerState(active=True, profile="calls", interface="en0", gateway="10.0.0.1")
            context = build_agent_context(state, db, provider="all", include_live=False)
            self.assertEqual(context["state"]["interface"], "en0")
            self.assertIsNone(context["live_snapshot"])
            self.assertIn("Meridian does not store provider passwords, API keys, or tokens.", context["safety_boundaries"])

    def test_render_context_marks_disabled_live_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = MetricsDB(Path(tmp) / "metrics.sqlite3")
            context = build_agent_context(StabilizerState(), db, include_live=False)
            rendered = render_agent_context_markdown(context)
            self.assertIn("live collection disabled", rendered)
            self.assertIn("Raw JSON", rendered)


if __name__ == "__main__":
    unittest.main()

