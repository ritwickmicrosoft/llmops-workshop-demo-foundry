"""
LLMOps Workshop - Model Swap & Re-Evaluation Workflow
======================================================
Demonstrates how to safely replace a model and automatically re-run evaluations,
comparing results side-by-side to decide whether to promote the change.

Workflow:
  1. Run evaluation against the CURRENT model (e.g., gpt-4o)
  2. Swap to the CANDIDATE model (e.g., gpt-4o-mini)
  3. Run the SAME evaluation against the candidate
  4. Compare results side-by-side
  5. Apply promotion gate: candidate must meet thresholds AND not regress

Usage:
  python model_swap_eval.py                                        # Default: gpt-4o vs gpt-4o-mini
  python model_swap_eval.py --current gpt-4o --candidate gpt-4o-mini
  python model_swap_eval.py --candidate gpt-4o-mini --skip-current  # Only eval candidate (if current results exist)
  python model_swap_eval.py --ci                                    # CI mode: exit 1 if candidate fails

Authentication: DefaultAzureCredential (RBAC)
Microsoft Foundry: foundry-llmops-canadaeast / proj-llmops-demo
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path
from azure.identity import DefaultAzureCredential
from azure.ai.evaluation import (
    GroundednessEvaluator,
    RelevanceEvaluator,
    SimilarityEvaluator,
    FluencyEvaluator,
    evaluate,
)
from azure.ai.projects import AIProjectClient


# =============================================================================
# Configuration - Microsoft Foundry (foundry-llmops-canadaeast)
# =============================================================================
FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://foundry-llmops-canadaeast.services.ai.azure.com/api/projects/proj-llmops-demo"
)
AZURE_PROJECT_NAME = os.environ.get("AZURE_PROJECT_NAME", "proj-llmops-demo")

EVAL_DATA_PATH = Path(__file__).parent.parent / "02-evaluation" / "eval_dataset.jsonl"
RESULTS_PATH = Path(__file__).parent / "comparison_results"
MAX_SAMPLES = int(os.environ.get("EVAL_MAX_SAMPLES", "10"))

# Promotion gate thresholds
THRESHOLDS = {
    "groundedness": 4.0,
    "relevance": 4.0,
    "similarity": 3.5,
    "fluency": 4.0,
}

# Maximum allowed regression (candidate can be at most this much worse than current)
MAX_REGRESSION = 0.5


def parse_args():
    parser = argparse.ArgumentParser(description="Model Swap + Re-Evaluation Workflow")
    parser.add_argument("--current", default="gpt-4o", help="Current (baseline) model name")
    parser.add_argument("--candidate", default="gpt-4o-mini", help="Candidate (replacement) model name")
    parser.add_argument("--skip-current", action="store_true", help="Skip evaluating current model (use cached)")
    parser.add_argument("--max-samples", type=int, default=None)
    parser.add_argument("--max-regression", type=float, default=MAX_REGRESSION,
                        help="Max allowed regression per metric (default 0.5)")
    parser.add_argument("--ci", action="store_true", help="CI mode: exit code 1 if swap not recommended")
    return parser.parse_args()


def load_data(file_path: Path) -> list[dict]:
    data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def run_evaluation_for_model(model: str, eval_data: list, aoai_endpoint: str,
                              results_dir: Path) -> dict:
    """Run full 4-metric evaluation for a given model."""
    print(f"\n  {'='*50}")
    print(f"  Evaluating model: {model}")
    print(f"  {'='*50}")

    os.environ["AZURE_OPENAI_ENDPOINT"] = aoai_endpoint
    os.environ["AZURE_OPENAI_DEPLOYMENT"] = model
    os.environ["AZURE_OPENAI_API_VERSION"] = "2024-06-01"

    model_config = {"azure_endpoint": aoai_endpoint, "azure_deployment": model}

    evaluators = {
        "groundedness": GroundednessEvaluator(model_config=model_config),
        "relevance": RelevanceEvaluator(model_config=model_config),
        "similarity": SimilarityEvaluator(model_config=model_config),
        "fluency": FluencyEvaluator(model_config=model_config),
    }

    # Prepare temp data
    temp_data = []
    for item in eval_data:
        temp_data.append({
            "question": item["question"],
            "ground_truth": item["ground_truth"],
            "context": item.get("context", ""),
            "response": item["ground_truth"],
        })

    results_dir.mkdir(parents=True, exist_ok=True)
    temp_file = results_dir / f"temp_{model.replace('-','_')}.jsonl"
    with open(temp_file, "w", encoding="utf-8") as f:
        for row in temp_data:
            f.write(json.dumps(row) + "\n")

    results = evaluate(
        data=str(temp_file),
        evaluators=evaluators,
        evaluator_config={
            "groundedness": {"question": "${data.question}", "context": "${data.context}", "response": "${data.response}"},
            "relevance": {"question": "${data.question}", "context": "${data.context}", "response": "${data.response}"},
            "similarity": {"question": "${data.question}", "ground_truth": "${data.ground_truth}", "response": "${data.response}"},
            "fluency": {"response": "${data.response}"},
        },
    )

    metrics = results.get("metrics", {})
    parsed = {}
    for m in ["groundedness", "relevance", "similarity", "fluency"]:
        val = metrics.get(f"{m}.{m}", metrics.get(f"mean_{m}", metrics.get(m, None)))
        parsed[m] = round(val, 3) if isinstance(val, (int, float)) else None

    # Display
    for m, v in parsed.items():
        icon = "✓" if v and v >= THRESHOLDS.get(m, 4.0) else "✗"
        print(f"    {icon} {m.capitalize():15} {v:.2f}/5.0" if v else f"    ? {m.capitalize():15} N/A")

    return {"model": model, "metrics": parsed, "raw_metrics": metrics, "rows": results.get("rows", [])}


def compare_models(current_result: dict, candidate_result: dict, max_regression: float) -> dict:
    """Compare two model evaluation results and produce a recommendation."""
    comparison = {}
    all_pass_threshold = True
    all_pass_regression = True

    for m in ["groundedness", "relevance", "similarity", "fluency"]:
        cur = current_result["metrics"].get(m)
        cand = candidate_result["metrics"].get(m)
        threshold = THRESHOLDS.get(m, 4.0)

        if cand is None:
            comparison[m] = {"current": cur, "candidate": None, "delta": None,
                             "meets_threshold": False, "regression_ok": False}
            all_pass_threshold = False
            all_pass_regression = False
            continue

        delta = (cand - cur) if cur is not None else None
        meets = cand >= threshold
        regression_ok = delta is None or delta >= -max_regression

        if not meets:
            all_pass_threshold = False
        if not regression_ok:
            all_pass_regression = False

        comparison[m] = {
            "current": cur, "candidate": cand, "delta": round(delta, 3) if delta is not None else None,
            "meets_threshold": meets, "regression_ok": regression_ok
        }

    recommend = all_pass_threshold and all_pass_regression
    return {
        "recommend_swap": recommend,
        "all_thresholds_met": all_pass_threshold,
        "no_regression": all_pass_regression,
        "details": comparison,
    }


def generate_comparison_html(file_path: Path, current_result: dict,
                              candidate_result: dict, comparison: dict, timestamp: str):
    """Generate side-by-side comparison HTML report."""
    recommend = comparison["recommend_swap"]
    banner_color = "#10b981" if recommend else "#ef4444"
    banner_text = "RECOMMENDATION: SAFE TO SWAP" if recommend else "RECOMMENDATION: DO NOT SWAP"

    rows_html = ""
    for m in ["groundedness", "relevance", "similarity", "fluency"]:
        d = comparison["details"][m]
        cur_val = f"{d['current']:.2f}" if d["current"] is not None else "N/A"
        cand_val = f"{d['candidate']:.2f}" if d["candidate"] is not None else "N/A"
        delta = d.get("delta")
        if delta is not None:
            delta_color = "#10b981" if delta >= 0 else "#ef4444"
            delta_str = f"<span style='color:{delta_color}'>{delta:+.2f}</span>"
        else:
            delta_str = "N/A"
        thresh_icon = "&#x2705;" if d["meets_threshold"] else "&#x274C;"
        reg_icon = "&#x2705;" if d["regression_ok"] else "&#x274C;"
        rows_html += f"<tr><td><strong>{m.capitalize()}</strong></td><td>{cur_val}</td><td>{cand_val}</td><td>{delta_str}</td><td>{thresh_icon}</td><td>{reg_icon}</td></tr>"

    html = f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Model Comparison - {timestamp}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);color:#e2e8f0;min-height:100vh;padding:40px 20px}}
.container{{max-width:900px;margin:0 auto}}
.banner{{text-align:center;padding:18px;border-radius:12px;font-size:22px;font-weight:700;margin-bottom:28px;background:{banner_color};color:#fff}}
.header{{text-align:center;margin-bottom:28px;padding:20px;background:rgba(30,41,59,.8);border-radius:16px;border:1px solid rgba(148,163,184,.1)}}
.header h1{{font-size:24px;margin-bottom:6px;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.header p{{color:#94a3b8;font-size:13px}}
.models{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px}}
.model-card{{background:rgba(30,41,59,.9);border-radius:12px;padding:20px;border:1px solid rgba(148,163,184,.1);text-align:center}}
.model-card h3{{color:#94a3b8;font-size:13px;margin-bottom:8px}}
.model-card .name{{font-size:28px;font-weight:700;color:#60a5fa}}
.table-wrap{{background:rgba(30,41,59,.9);border-radius:12px;padding:24px;border:1px solid rgba(148,163,184,.1);margin-bottom:24px}}
.table-wrap h2{{font-size:18px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:14px}}
th,td{{padding:12px;text-align:center;border-bottom:1px solid #334155}}
th{{color:#94a3b8;font-weight:600;background:rgba(15,23,42,.5)}}
td:first-child{{text-align:left}}
.footer{{text-align:center;margin-top:28px;color:#64748b;font-size:11px}}
</style></head>
<body><div class="container">
    <div class="banner">{banner_text}</div>
    <div class="header">
        <h1>Model Swap Comparison Report</h1>
        <p>{datetime.now().strftime("%B %d, %Y at %I:%M %p")} | Microsoft Foundry ({AZURE_PROJECT_NAME})</p>
    </div>
    <div class="models">
        <div class="model-card"><h3>CURRENT (Baseline)</h3><div class="name">{current_result["model"]}</div></div>
        <div class="model-card"><h3>CANDIDATE (Replacement)</h3><div class="name">{candidate_result["model"]}</div></div>
    </div>
    <div class="table-wrap">
        <h2>Side-by-Side Metrics</h2>
        <table><thead><tr><th>Metric</th><th>Current</th><th>Candidate</th><th>Delta</th><th>Threshold</th><th>Regression</th></tr></thead>
        <tbody>{rows_html}</tbody></table>
    </div>
    <div class="table-wrap">
        <h2>Verdict</h2>
        <p style="font-size:15px;line-height:1.8;">
            All thresholds met: {"&#x2705; Yes" if comparison["all_thresholds_met"] else "&#x274C; No"}<br/>
            No excessive regression: {"&#x2705; Yes" if comparison["no_regression"] else "&#x274C; No"}<br/>
            <strong>Recommendation: {"Proceed with swap" if recommend else "Do NOT swap — address regressions first"}</strong>
        </p>
    </div>
    <div class="footer">LLMOps Workshop | Model Swap Workflow | Microsoft Foundry</div>
</div></body></html>'''

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    args = parse_args()
    max_samples = args.max_samples or MAX_SAMPLES

    print("=" * 60)
    print("  Model Swap & Re-Evaluation Workflow")
    print("  Microsoft Foundry")
    print("=" * 60)
    print(f"\n  Current model:   {args.current}")
    print(f"  Candidate model: {args.candidate}")
    print(f"  Max regression:  {args.max_regression}")

    # --- Auth ---
    credential = DefaultAzureCredential()
    project_client = AIProjectClient(endpoint=FOUNDRY_PROJECT_ENDPOINT, credential=credential)

    try:
        aoai_connection = project_client.connections.get("aoai-connection")
        aoai_endpoint = aoai_connection.target
    except Exception:
        aoai_endpoint = (
            FOUNDRY_PROJECT_ENDPOINT.split("/api/projects/")[0]
            .replace(".services.ai.azure.com", ".cognitiveservices.azure.com") + "/"
        )

    # --- Data ---
    eval_data = load_data(EVAL_DATA_PATH)
    if len(eval_data) > max_samples:
        eval_data = eval_data[:max_samples]
    print(f"\n  Evaluation samples: {len(eval_data)}")

    RESULTS_PATH.mkdir(parents=True, exist_ok=True)

    # --- Evaluate current model ---
    if args.skip_current:
        # Look for most recent cached result
        cached = sorted(RESULTS_PATH.glob("comparison_*.json"), reverse=True)
        if cached:
            with open(cached[0]) as f:
                prev = json.load(f)
            current_result = prev.get("current_result", {})
            print(f"\n  Using cached current model results from {cached[0].name}")
        else:
            print("\n  No cached results found — evaluating current model...")
            current_result = run_evaluation_for_model(args.current, eval_data, aoai_endpoint, RESULTS_PATH)
    else:
        current_result = run_evaluation_for_model(args.current, eval_data, aoai_endpoint, RESULTS_PATH)

    # --- Evaluate candidate model ---
    candidate_result = run_evaluation_for_model(args.candidate, eval_data, aoai_endpoint, RESULTS_PATH)

    # --- Compare ---
    print("\n" + "=" * 60)
    print("  Side-by-Side Comparison")
    print("=" * 60)

    comparison = compare_models(current_result, candidate_result, args.max_regression)

    print(f"\n  {'Metric':<15} {'Current':>10} {'Candidate':>10} {'Delta':>8} {'Threshold':>10} {'Regression':>11}")
    print("  " + "-" * 65)
    for m in ["groundedness", "relevance", "similarity", "fluency"]:
        d = comparison["details"][m]
        cur = f"{d['current']:.2f}" if d["current"] is not None else "N/A"
        cand = f"{d['candidate']:.2f}" if d["candidate"] is not None else "N/A"
        delta = f"{d['delta']:+.2f}" if d["delta"] is not None else "N/A"
        t_icon = "✓" if d["meets_threshold"] else "✗"
        r_icon = "✓" if d["regression_ok"] else "✗"
        print(f"  {m.capitalize():<15} {cur:>10} {cand:>10} {delta:>8} {t_icon:>10} {r_icon:>11}")

    print("\n  " + "-" * 65)
    if comparison["recommend_swap"]:
        print("  ✅ RECOMMENDATION: Safe to swap to", args.candidate)
    else:
        print("  ❌ RECOMMENDATION: Do NOT swap to", args.candidate)
        if not comparison["all_thresholds_met"]:
            print("     → Candidate does not meet all quality thresholds")
        if not comparison["no_regression"]:
            print(f"     → Candidate regresses more than {args.max_regression} on some metrics")

    # --- Save ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "timestamp": timestamp,
        "current_result": current_result,
        "candidate_result": candidate_result,
        "comparison": comparison,
        "thresholds": THRESHOLDS,
        "max_regression": args.max_regression,
    }

    json_file = RESULTS_PATH / f"comparison_{timestamp}.json"
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\n  ✓ JSON results: {json_file}")

    html_file = RESULTS_PATH / f"comparison_{timestamp}.html"
    generate_comparison_html(html_file, current_result, candidate_result, comparison, timestamp)
    print(f"  ✓ HTML report: {html_file}")

    print("\n" + "=" * 60)

    if args.ci:
        sys.exit(0 if comparison["recommend_swap"] else 1)


if __name__ == "__main__":
    main()
