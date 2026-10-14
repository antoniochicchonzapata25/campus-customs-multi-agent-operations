"""LIVE smoke test: real gpt-6-luna via Portkey + real MCP server + real audit trail.

Not collected by pytest (it costs tokens). Run from backend/:
    python tests/live_smoke.py

It deliberately does NOT work on any desk ticket. Inventory checks a product
that no ticket mentions (CC-HAT-BLUE) and must delegate the margin question to
Accounting, which exercises live specialist-to-specialist delegation. Every
tool the agents can reach is read-only, so the databases cannot change; this
script checks that by hashing them before and after. Events are appended to
output/audit_trail.json with run_type "smoke_test".
"""

import asyncio
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import RunLimits  # noqa: E402
from team import CampusCustomsTeam  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DBS = [ROOT / "data" / "campus_customs.db", ROOT / "data" / "campus_customs_new.db"]

TASK = (
    "LIVE SMOKE TEST - this is not a desk ticket; do not work on tickets 101-103. "
    "Check how many CC-HAT-BLUE (size OS) are on hand. Then delegate to accounting and ask them to "
    "report the unit cost, list price, and margin per unit for CC-HAT-BLUE. Do not prepare any "
    "payment or purchase order. Return a short report with both results."
)


async def main() -> int:
    before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in DBS]
    team = CampusCustomsTeam(limits=RunLimits(max_delegations_per_run=2, team_request_limit=12,
                                              team_total_tokens_limit=80_000))
    result = await team.run("inventory", TASK, run_type="smoke_test")
    after = [hashlib.sha256(p.read_bytes()).hexdigest() for p in DBS]
    print(json.dumps(result.model_dump(mode="json"), indent=2))
    print("databases unchanged:", before == after)
    return 0 if result.stopped_reason == "completed" and before == after else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
