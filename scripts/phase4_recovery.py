"""Run deterministic constrained recovery for Phase 3 scenarios."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from maritime.phase3 import load_json, validate_scenario
from maritime.phase4 import write_outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-scenario", "recover", "run-examples"))
    parser.add_argument("--dataset", type=Path, default=ROOT/"data/builds/research_1500")
    parser.add_argument("--scenario", type=Path)
    parser.add_argument("--examples", type=Path, default=ROOT/"examples/phase3")
    parser.add_argument("--policy", type=Path, default=ROOT/"config/recovery_policy.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    ports = load_json(args.dataset/"ports.json")
    services = load_json(args.dataset/"services.json")
    if args.command == "run-examples":
        paths = sorted(args.examples.glob("*.json"))
    else:
        if args.scenario is None:
            parser.error("--scenario is required")
        paths = [args.scenario]
    rows = []
    for path in paths:
        raw = load_json(path)
        validated = validate_scenario(raw, ports, services)
        if args.command == "validate-scenario":
            rows.append({"scenario_id": validated["scenario_id"], "validation_status": "passed"})
            continue
        output = (args.output or ROOT/"data/simulations/phase4")
        if args.command == "run-examples" or args.output is None:
            output = output/path.stem
        rows.append(write_outputs(args.dataset, raw, args.policy, output))
    print(json.dumps(rows if len(rows) != 1 else rows[0],indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
