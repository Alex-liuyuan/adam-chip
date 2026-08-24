#!/usr/bin/env python3
"""Apply the SDK release gate to security, verification and package reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--security-handoff", required=True)
    parser.add_argument("--verification-handoff", required=True)
    parser.add_argument("--image-report", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    release = json.loads(Path(args.release).read_text(encoding="utf-8"))
    security = json.loads(Path(args.security_handoff).read_text(encoding="utf-8"))
    verification = json.loads(Path(args.verification_handoff).read_text(encoding="utf-8"))
    image = json.loads(Path(args.image_report).read_text(encoding="utf-8"))
    candidate = bool(release.get("ok")) and bool(security.get("evidence", {}).get("signature_pass")) and bool(verification.get("evidence", {}).get("virtual_execution_pass"))
    self_hosted = bool(image.get("evidence", {}).get("self_hosted_boot_chain"))
    physical = bool(verification.get("evidence", {}).get("boot_marker_pass") and verification.get("evidence", {}).get("flash_readback_pass"))
    evidence = {
        "sdk_candidate_ready": candidate,
        "security_handoff_bound": security.get("from_agent") == "SecurityAgent",
        "verification_handoff_bound": verification.get("from_agent") == "VerificationAgent",
    }
    report = {
        "ok": all(evidence.values()),
        "evidence": evidence,
        "release_status": {
            "self_hosted_boot_chain": self_hosted,
            "physical_release_ready": candidate and self_hosted and physical,
        },
        "not_claimed": ["physical-board release readiness"],
    }
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
