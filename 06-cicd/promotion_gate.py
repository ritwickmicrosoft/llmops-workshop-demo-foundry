"""
LLMOps Workshop - Promotion Gate Logic
========================================
Standalone gate checker that can be called from CI/CD pipelines.

Checks:
  1. Evaluation quality gate (from enhanced eval JSON output)
  2. Content safety pass rate gate
  3. Model comparison regression gate

Usage (from pipeline):
  python promotion_gate.py --check-eval --results eval_results.json --threshold 4.0
  python promotion_gate.py --check-content-safety --results-dir 03-content-safety/test_results --min-pass-rate 90
  python promotion_gate.py --check-comparison --results comparison_results.json --max-regression 0.5

Exit codes:
  0 = Gate PASSED
  1 = Gate FAILED
  2 = Error (missing files, bad input)

Microsoft Foundry: foundry-llmops-canadaeast / proj-llmops-demo
"""

import sys
import json
import argparse
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Promotion Gate Checker for CI/CD Pipelines")

    # Gate type (pick one)
    parser.add_argument("--check-eval", action="store_true", help="Check evaluation quality gate")
    parser.add_argument("--check-content-safety", action="store_true", help="Check content safety pass rate")
    parser.add_argument("--check-comparison", action="store_true", help="Check model comparison regression")

    # Inputs
    parser.add_argument("--results", default=None, help="Path to results JSON file")
    parser.add_argument("--results-dir", default=None, help="Path to results directory (uses latest file)")

    # Thresholds
    parser.add_argument("--threshold", type=float, default=4.0, help="Min metric score for eval gate")
    parser.add_argument("--min-pass-rate", type=float, default=90.0, help="Min content safety pass rate (%)")
    parser.add_argument("--max-regression", type=float, default=0.5, help="Max regression allowed per metric")

    return parser.parse_args()


def find_latest_json(directory: Path) -> Path | None:
    """Find the most recently created JSON file in a directory."""
    jsons = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return jsons[0] if jsons else None


def check_eval_gate(results_path: str, threshold: float) -> bool:
    """
    Check whether evaluation metrics meet the promotion threshold.
    Reads the JSON output from run_evaluation_enhanced.py.
    """
    path = Path(results_path)
    if not path.exists():
        print(f"  ERROR: Results file not found: {path}")
        sys.exit(2)

    with open(path) as f:
        data = json.load(f)

    # Check if gate_result is embedded (from enhanced eval)
    gate = data.get("gate_result")
    if gate:
        passed = gate.get("passed", False)
        print(f"  Evaluation gate: {'PASSED' if passed else 'FAILED'}")
        for m, detail in gate.get("metrics", {}).items():
            icon = "✓" if detail.get("passed") else "✗"
            print(f"    {icon} {m}: {detail.get('value', 'N/A')} (threshold: {detail.get('threshold', threshold)})")
        return passed

    # Fallback: check raw metrics
    metrics = data.get("metrics", {})
    all_pass = True
    for metric_name in ["groundedness", "relevance", "similarity", "fluency"]:
        val = metrics.get(f"{metric_name}.{metric_name}",
                         metrics.get(metric_name, None))
        if val is None or not isinstance(val, (int, float)):
            print(f"    ? {metric_name}: N/A")
            continue
        passed = val >= threshold
        icon = "✓" if passed else "✗"
        print(f"    {icon} {metric_name}: {val:.2f} (threshold: {threshold})")
        if not passed:
            all_pass = False

    print(f"\n  Evaluation gate: {'PASSED' if all_pass else 'FAILED'}")
    return all_pass


def check_content_safety_gate(results_dir: str, min_pass_rate: float) -> bool:
    """
    Check content safety test pass rate from the latest results JSON.
    """
    directory = Path(results_dir)
    if not directory.exists():
        print(f"  ERROR: Results directory not found: {directory}")
        sys.exit(2)

    latest = find_latest_json(directory)
    if not latest:
        print(f"  ERROR: No JSON results found in: {directory}")
        sys.exit(2)

    with open(latest) as f:
        data = json.load(f)

    total = data.get("total_tests", 0)
    passed = data.get("passed", 0)
    pass_rate = (passed / total * 100) if total > 0 else 0

    print(f"  Content Safety Results ({latest.name}):")
    print(f"    Total tests:  {total}")
    print(f"    Passed:       {passed}")
    print(f"    Pass rate:    {pass_rate:.1f}% (minimum: {min_pass_rate}%)")

    gate_passed = pass_rate >= min_pass_rate
    print(f"\n  Content safety gate: {'PASSED' if gate_passed else 'FAILED'}")
    return gate_passed


def check_comparison_gate(results_path: str, max_regression: float) -> bool:
    """
    Check model comparison results — candidate must not regress excessively.
    """
    path = Path(results_path) if results_path else None

    # If path is a directory, find latest
    if path and path.is_dir():
        path = find_latest_json(path)
    elif path and not path.exists() and Path(results_path).parent.is_dir():
        path = find_latest_json(Path(results_path).parent)

    if not path or not path.exists():
        print(f"  ERROR: Comparison results not found")
        sys.exit(2)

    with open(path) as f:
        data = json.load(f)

    comparison = data.get("comparison", {})
    recommend = comparison.get("recommend_swap", False)

    print(f"  Model Comparison Results ({path.name}):")
    print(f"    Recommend swap: {'YES' if recommend else 'NO'}")
    print(f"    All thresholds met: {'✓' if comparison.get('all_thresholds_met') else '✗'}")
    print(f"    No regression: {'✓' if comparison.get('no_regression') else '✗'}")

    for m, detail in comparison.get("details", {}).items():
        delta = detail.get("delta")
        delta_str = f"{delta:+.2f}" if delta is not None else "N/A"
        print(f"      {m}: current={detail.get('current', 'N/A')}, "
              f"candidate={detail.get('candidate', 'N/A')}, delta={delta_str}")

    print(f"\n  Comparison gate: {'PASSED' if recommend else 'FAILED'}")
    return recommend


def main():
    args = parse_args()

    print("=" * 50)
    print("  Promotion Gate Checker")
    print("=" * 50)

    if args.check_eval:
        results = args.results
        if not results and args.results_dir:
            latest = find_latest_json(Path(args.results_dir))
            results = str(latest) if latest else None
        if not results:
            print("  ERROR: Provide --results or --results-dir")
            sys.exit(2)
        passed = check_eval_gate(results, args.threshold)
        sys.exit(0 if passed else 1)

    elif args.check_content_safety:
        if not args.results_dir:
            print("  ERROR: Provide --results-dir for content safety check")
            sys.exit(2)
        passed = check_content_safety_gate(args.results_dir, args.min_pass_rate)
        sys.exit(0 if passed else 1)

    elif args.check_comparison:
        results = args.results or args.results_dir
        if not results:
            print("  ERROR: Provide --results or --results-dir")
            sys.exit(2)
        passed = check_comparison_gate(results, args.max_regression)
        sys.exit(0 if passed else 1)

    else:
        print("  ERROR: Specify a gate type: --check-eval, --check-content-safety, or --check-comparison")
        sys.exit(2)


if __name__ == "__main__":
    main()
