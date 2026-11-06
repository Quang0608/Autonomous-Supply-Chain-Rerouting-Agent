"""Validate and run Phase 3 temporal disruption scenarios."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from maritime.phase3 import ScenarioError, load_json, validate_scenario, write_outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate-scenario", "analyze-impact", "simulate-no-recovery"))
    parser.add_argument("--dataset", default=str(ROOT / "data/builds/research_1500"))
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--output", help="Output directory for analysis/simulation")
    parser.add_argument("--seed", type=int, default=42, help="Reserved for future stochastic extensions; current engine is deterministic")
    args = parser.parse_args()
    dataset = Path(args.dataset)
    raw = load_json(Path(args.scenario))
    ports, services = load_json(dataset / "ports.json"), load_json(dataset / "services.json")
    normalized = validate_scenario(raw, ports, services)
    if args.command == "validate-scenario":
        print(json.dumps({"validation_status": "passed", "scenario_id": normalized["scenario_id"], "events": len(normalized["events"]), "targets_checked": True}, indent=2))
        return 0
    output = Path(args.output) if args.output else ROOT / "data/simulations/phase3" / normalized["scenario_id"]
    summary = write_outputs(dataset, normalized, output, args.seed)
    print(json.dumps({"output_directory": str(output), "summary": summary}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ScenarioError, FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
