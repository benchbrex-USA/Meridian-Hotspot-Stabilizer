from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from .constants import ANCHOR, DOWNLOAD_PIPE, UPLOAD_PIPE
from .policy import Caps
from .system import build_pf_rules, format_mbit, validate_caps, validate_interface_name


AllowedOperation = Literal["apply-shaping", "clear-shaping", "service-install", "service-uninstall"]


@dataclass(frozen=True)
class PrivilegedCommandSpec:
    operation: AllowedOperation
    command: list[str]
    owned_resource: str
    reason: str


def build_apply_plan(interface: str, caps: Caps) -> list[PrivilegedCommandSpec]:
    validate_interface_name(interface)
    validate_caps(caps)
    return [
        PrivilegedCommandSpec(
            operation="apply-shaping",
            command=["dnctl", "pipe", str(UPLOAD_PIPE), "config", "bw", format_mbit(caps.upload_mbps), "queue", "50"],
            owned_resource=f"dummynet pipe {UPLOAD_PIPE}",
            reason="configure Meridian upload shaping pipe",
        ),
        PrivilegedCommandSpec(
            operation="apply-shaping",
            command=["dnctl", "pipe", str(DOWNLOAD_PIPE), "config", "bw", format_mbit(caps.download_mbps), "queue", "100"],
            owned_resource=f"dummynet pipe {DOWNLOAD_PIPE}",
            reason="configure Meridian download shaping pipe",
        ),
        PrivilegedCommandSpec(
            operation="apply-shaping",
            command=["pfctl", "-a", ANCHOR, "-f", "<rules-file>"],
            owned_resource=f"PF anchor {ANCHOR}",
            reason=f"load Meridian PF dummynet rules for {interface}",
        ),
    ]


def build_clear_plan(pf_token: str | None = None) -> list[PrivilegedCommandSpec]:
    plan = [
        PrivilegedCommandSpec(
            operation="clear-shaping",
            command=["pfctl", "-a", ANCHOR, "-F", "all"],
            owned_resource=f"PF anchor {ANCHOR}",
            reason="flush Meridian-owned PF anchor state",
        ),
        PrivilegedCommandSpec(
            operation="clear-shaping",
            command=["dnctl", "-q", "pipe", "delete", str(UPLOAD_PIPE), str(DOWNLOAD_PIPE)],
            owned_resource=f"dummynet pipes {UPLOAD_PIPE},{DOWNLOAD_PIPE}",
            reason="delete Meridian-owned dummynet pipes",
        ),
    ]
    if pf_token:
        plan.append(
            PrivilegedCommandSpec(
                operation="clear-shaping",
                command=["pfctl", "-X", "<pf-token>"],
                owned_resource="Meridian PF enable token",
                reason="release the PF token acquired by Meridian",
            )
        )
    return plan


def helper_contract(interface: str = "en0", caps: Caps | None = None) -> dict[str, object]:
    caps = caps or Caps(upload_mbps=10.0, download_mbps=25.0)
    return {
        "contract_version": 1,
        "authority": "The signed helper may execute only allowlisted Meridian operations.",
        "forbidden": [
            "editing /etc/pf.conf",
            "loading arbitrary PF anchors",
            "executing shell strings",
            "reading provider credentials",
            "changing non-Meridian dummynet pipes",
        ],
        "owned_anchor": ANCHOR,
        "owned_pipes": [UPLOAD_PIPE, DOWNLOAD_PIPE],
        "apply_plan_example": [asdict(item) for item in build_apply_plan(interface, caps)],
        "clear_plan_example": [asdict(item) for item in build_clear_plan("<redacted-token>")],
        "pf_rules_example": build_pf_rules(interface),
    }
