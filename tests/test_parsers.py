import unittest

from meridian_stabilizer.parsers import parse_default_route, parse_network_quality, parse_ping


class ParserTests(unittest.TestCase):
    def test_parse_default_route(self):
        output = """
   route to: default
destination: default
    gateway: 10.176.94.179
  interface: en0
"""
        route = parse_default_route(output)
        self.assertEqual(route.interface, "en0")
        self.assertEqual(route.gateway, "10.176.94.179")

    def test_parse_ping_macos(self):
        output = """
--- 1.1.1.1 ping statistics ---
8 packets transmitted, 8 packets received, 0.0% packet loss
round-trip min/avg/max/stddev = 41.959/159.302/301.374/100.383 ms
"""
        stats = parse_ping(output)
        self.assertEqual(stats.transmitted, 8)
        self.assertEqual(stats.received, 8)
        self.assertEqual(stats.loss_percent, 0.0)
        self.assertEqual(stats.avg_ms, 159.302)
        self.assertEqual(stats.stddev_ms, 100.383)

    def test_parse_network_quality_summary(self):
        output = """
==== SUMMARY ====
Uplink capacity: 44.514 Mbps
Downlink capacity: 354.382 Mbps
Uplink Responsiveness: Low (1.345 seconds | 44 RPM)
Downlink Responsiveness: Medium (207.721 milliseconds | 288 RPM)
Idle Latency: 62.460 milliseconds | 960 RPM
"""
        quality = parse_network_quality(output)
        self.assertEqual(quality.upload_mbps, 44.514)
        self.assertEqual(quality.download_mbps, 354.382)
        self.assertEqual(quality.upload_responsiveness, "Low")
        self.assertEqual(quality.download_responsiveness, "Medium")
        self.assertEqual(quality.idle_latency_ms, 62.46)

    def test_parse_network_quality_json(self):
        output = """
{
  "base_rtt" : 59.006359100341797,
  "dl_throughput" : 70322704,
  "interface_name" : "en0",
  "ul_throughput" : 44514000,
  "ul_responsiveness" : 44,
  "dl_responsiveness" : 632.2440185546875
}
"""
        quality = parse_network_quality(output)
        self.assertAlmostEqual(quality.upload_mbps, 44.514)
        self.assertAlmostEqual(quality.download_mbps, 70.322704)
        self.assertEqual(quality.interface, "en0")
        self.assertEqual(quality.base_rtt_ms, 59.006359100341797)
        self.assertEqual(quality.upload_responsiveness, "Low")
        self.assertEqual(quality.download_responsiveness, "Medium")


if __name__ == "__main__":
    unittest.main()
