import unittest

from meridian_stabilizer.diagnostics import ProbeStep, SiteProbe, diagnose_internet, normalize_target
from meridian_stabilizer.measurements import RuntimeSnapshot
from meridian_stabilizer.parsers import PingStats, RouteInfo


def _snapshot() -> RuntimeSnapshot:
    return RuntimeSnapshot(
        route=RouteInfo(interface="en0", gateway="10.0.0.1"),
        gateway_ping=None,
        internet_ping=PingStats(transmitted=4, received=4, loss_percent=0.0, min_ms=20.0, avg_ms=30.0, max_ms=40.0, stddev_ms=3.0),
        quality=None,
    )


def _probe(ok: bool, stage: str | None = None) -> SiteProbe:
    return SiteProbe(
        target="example.com",
        url="https://example.com/",
        host="example.com",
        port=443,
        scheme="https",
        ok=ok,
        failure_stage=stage,
        summary="ok" if ok else f"{stage} failed",
        status_code=204 if ok else None,
        steps=(ProbeStep(stage or "http", ok, "detail"),),
    )


class DiagnosticsTests(unittest.TestCase):
    def test_normalize_target_adds_https_scheme(self):
        self.assertEqual(normalize_target("example.com"), "https://example.com/")

    def test_diagnosis_marks_all_sites_reachable(self):
        diagnosis = diagnose_internet(_snapshot(), (_probe(True),))

        self.assertIn("tested sites are reachable", diagnosis.likely_cause)
        self.assertEqual(len(diagnosis.recommendations), 2)

    def test_diagnosis_identifies_dns_failures(self):
        diagnosis = diagnose_internet(_snapshot(), (_probe(False, "dns"), _probe(False, "dns")))

        self.assertIn("DNS is failing", diagnosis.likely_cause)

    def test_diagnosis_prioritizes_missing_route(self):
        snapshot = RuntimeSnapshot(route=None, gateway_ping=None, internet_ping=None, quality=None, errors=("default route unavailable",))

        diagnosis = diagnose_internet(snapshot, (_probe(False, "tcp"),))

        self.assertIn("default route", diagnosis.likely_cause)


if __name__ == "__main__":
    unittest.main()
