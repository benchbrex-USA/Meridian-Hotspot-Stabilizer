import tarfile
import tempfile
import unittest
from pathlib import Path

from meridian_stabilizer.bundle import create_diagnostic_bundle
from meridian_stabilizer.database import MetricsDB
from meridian_stabilizer.state import StabilizerState, StateStore


class BundleTests(unittest.TestCase):
    def test_bundle_redacts_pf_token(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            store = StateStore(state_dir)
            store.save(StabilizerState(active=True, pf_token="secret-token"))
            db = MetricsDB(state_dir / "metrics.sqlite3")
            db.record_event("test", "event")

            bundle = create_diagnostic_bundle(store=store, db=db, output_dir=Path(tmp), include_live=False)

            self.assertTrue(bundle.path.exists())
            with tarfile.open(bundle.path, "r:gz") as archive:
                state_member = next(member for member in archive.getmembers() if member.name.endswith("state.redacted.json"))
                content = archive.extractfile(state_member).read().decode("utf-8")
            self.assertIn("[redacted]", content)
            self.assertNotIn("secret-token", content)


if __name__ == "__main__":
    unittest.main()
