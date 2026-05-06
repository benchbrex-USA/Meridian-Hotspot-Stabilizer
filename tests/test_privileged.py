import unittest

from meridian_stabilizer.constants import ANCHOR, DOWNLOAD_PIPE, UPLOAD_PIPE
from meridian_stabilizer.policy import Caps
from meridian_stabilizer.privileged import build_apply_plan, build_clear_plan, helper_contract


class PrivilegedContractTests(unittest.TestCase):
    def test_apply_plan_is_narrowly_owned(self):
        plan = build_apply_plan("en0", Caps(upload_mbps=10.0, download_mbps=25.0))
        resources = [item.owned_resource for item in plan]

        self.assertIn(f"dummynet pipe {UPLOAD_PIPE}", resources)
        self.assertIn(f"dummynet pipe {DOWNLOAD_PIPE}", resources)
        self.assertIn(f"PF anchor {ANCHOR}", resources)

    def test_clear_plan_redacts_token_placeholder(self):
        plan = build_clear_plan("token-value")

        self.assertEqual(plan[-1].command, ["pfctl", "-X", "<pf-token>"])

    def test_contract_forbids_general_command_runner(self):
        contract = helper_contract("en0", Caps(upload_mbps=10.0, download_mbps=25.0))

        self.assertIn("executing shell strings", contract["forbidden"])
        self.assertEqual(contract["owned_pipes"], [UPLOAD_PIPE, DOWNLOAD_PIPE])


if __name__ == "__main__":
    unittest.main()
