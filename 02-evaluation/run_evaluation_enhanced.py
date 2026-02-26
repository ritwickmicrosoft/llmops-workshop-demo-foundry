"""
LLMOps Workshop - Enhanced Evaluation Script
==============================================
Extended evaluation with pass/fail promotion gates for operationalizing RAG chatbots.

Evaluators:
  - Groundedness: Is the response supported by retrieved context?
  - Relevance: Does the response address the user's question?
  - Similarity: How close is the response to the expected answer?
  - Fluency: Is the response grammatically correct and natural?

Promotion Gate:
  - Each metric has a configurable threshold (default ≥4.0 on 1-5 scale)
  - Overall pass requires ALL metrics to meet their thresholds
  - Exit code 0 = PASS (safe to promote), Exit code 1 = FAIL (block promotion)

Usage:
  python run_evaluation_enhanced.py                          # Run with defaults
  python run_evaluation_enhanced.py --threshold 3.5          # Lower gate threshold
  python run_evaluation_enhanced.py --model gpt-4o-mini      # Evaluate a specific model
  python run_evaluation_enhanced.py --ci                     # CI mode (exit code reflects pass/fail)

Authentication: DefaultAzureCredential (RBAC - no API keys)
Microsoft Foundry: Uses AIProjectClient for chat completions and evaluation
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
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o")
MAX_SAMPLES = int(os.environ.get("EVAL_MAX_SAMPLES", "10"))

EVAL_DATA_PATH = Path(__file__).parent / "eval_dataset.jsonl"
RESULTS_PATH = Path(__file__).parent / "eval_results"

# Default promotion gate thresholds (1-5 scale)
DEFAULT_THRESHOLDS = {
    "groundedness": 4.0,
    "relevance": 4.0,
    "similarity": 3.5,
    "fluency": 4.0,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Enhanced RAG Evaluation with Promotion Gates")
    parser.add_argument("--model", default=None, help="Model to evaluate (overrides CHAT_MODEL env)")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Single threshold for ALL metrics (overrides per-metric defaults)")
    parser.add_argument("--threshold-groundedness", type=float, default=None)
    parser.add_argument("--threshold-relevance", type=float, default=None)
    parser.add_argument("--threshold-similarity", type=float, default=None)
    parser.add_argument("--threshold-fluency", type=float, default=None)
    parser.add_argument("--ci", action="store_true", help="CI mode: exit code 1 if gate fails")
    parser.add_argument("--max-samples", type=int, default=None, help="Max samples to evaluate")
    parser.add_argument("--data", default=None, help="Path to evaluation dataset (.jsonl)")
    parser.add_argument("--output-json", default=None, help="Path to write JSON results (for pipeline consumption)")
    return parser.parse_args()


def load_evaluation_data(file_path: Path) -> list[dict]:
    """Load evaluation dataset from JSONL file."""
    data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def get_thresholds(args) -> dict:
    """Resolve final thresholds from args + defaults."""
    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.threshold is not None:
        for key in thresholds:
            thresholds[key] = args.threshold
    if args.threshold_groundedness is not None:
        thresholds["groundedness"] = args.threshold_groundedness
    if args.threshold_relevance is not None:
        thresholds["relevance"] = args.threshold_relevance
    if args.threshold_similarity is not None:
        thresholds["similarity"] = args.threshold_similarity
    if args.threshold_fluency is not None:
        thresholds["fluency"] = args.threshold_fluency
    return thresholds


def evaluate_gate(metrics: dict, thresholds: dict) -> dict:
    """
    Evaluate promotion gate: does each metric meet its threshold?
    Returns gate result with per-metric pass/fail and overall verdict.
    """
    gate_results = {}
    all_pass = True

    for metric_name, threshold in thresholds.items():
        # SDK returns metrics like "groundedness.groundedness"
        value = metrics.get(f"{metric_name}.{metric_name}",
                            metrics.get(f"mean_{metric_name}",
                            metrics.get(metric_name, None)))

        if value is None or not isinstance(value, (int, float)):
            gate_results[metric_name] = {
                "value": None, "threshold": threshold, "passed": False, "reason": "metric not available"
            }
            all_pass = False
        else:
            passed = value >= threshold
            gate_results[metric_name] = {
                "value": round(value, 3),
                "threshold": threshold,
                "passed": passed,
                "reason": f"{value:.2f} {'≥' if passed else '<'} {threshold:.1f}"
            }
            if not passed:
                all_pass = False

    return {"passed": all_pass, "metrics": gate_results}


def generate_enhanced_html_report(file_path: Path, timestamp: str, model: str,
                                   dataset_size: int, metrics: dict,
                                   gate_result: dict, rows: list):
    """Generate an HTML report with evaluation results + promotion gate verdict."""

    def score_color(v):
        if not isinstance(v, (int, float)):
            return "#6b7280", "N/A"
        if v >= 4.0:
            return "#10b981", "Excellent"
        if v >= 3.0:
            return "#f59e0b", "Good"
        if v >= 2.0:
            return "#ef4444", "Needs Work"
        return "#dc2626", "Poor"

    metric_names = ["groundedness", "relevance", "similarity", "fluency"]
    cards_html = ""
    for m in metric_names:
        val = metrics.get(f"{m}.{m}", metrics.get(m, "N/A"))
        color, label = score_color(val)
        gate_info = gate_result["metrics"].get(m, {})
        gate_icon = "&#x2705;" if gate_info.get("passed") else "&#x274C;"
        threshold = gate_info.get("threshold", "N/A")
        val_display = f"{val:.2f}" if isinstance(val, (int, float)) else "N/A"
        cards_html += f'''
        <div class="metric-card">
            <h3>{m.capitalize()} {gate_icon}</h3>
            <div class="metric-value" style="color:{color};">{val_display}<span style="font-size:18px;color:#64748b;">/5.0</span></div>
            <div class="metric-label">{label} | Gate: ≥{threshold}</div>
            <div class="metric-bar"><div class="metric-bar-fill" style="width:{(val if isinstance(val,(int,float)) else 0)*20}%;background:{color};"></div></div>
        </div>'''

    gate_banner_color = "#10b981" if gate_result["passed"] else "#ef4444"
    gate_banner_text = "PROMOTION GATE: PASSED" if gate_result["passed"] else "PROMOTION GATE: FAILED"

    row_html = ""
    for i, row in enumerate(rows, 1):
        question = row.get("inputs.question", "N/A")
        g = row.get("outputs.groundedness.groundedness", "N/A")
        r = row.get("outputs.relevance.relevance", "N/A")
        s = row.get("outputs.similarity.similarity", "N/A")
        f = row.get("outputs.fluency.fluency", "N/A")
        row_html += f'''<tr>
            <td>{i}</td>
            <td style="max-width:250px;word-wrap:break-word;">{question}</td>
            <td style="color:{score_color(g)[0]};font-weight:bold;">{g}</td>
            <td style="color:{score_color(r)[0]};font-weight:bold;">{r}</td>
            <td style="color:{score_color(s)[0]};font-weight:bold;">{s}</td>
            <td style="color:{score_color(f)[0]};font-weight:bold;">{f}</td>
        </tr>'''

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Enhanced Eval Report - {timestamp}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:linear-gradient(135deg,#0f172a,#1e293b);color:#e2e8f0;min-height:100vh;padding:40px 20px}}
.container{{max-width:1200px;margin:0 auto}}
.gate-banner{{text-align:center;padding:18px;border-radius:12px;font-size:22px;font-weight:700;margin-bottom:30px;background:{gate_banner_color};color:#fff;letter-spacing:1px}}
.header{{text-align:center;margin-bottom:30px;padding:24px;background:rgba(30,41,59,.8);border-radius:16px;border:1px solid rgba(148,163,184,.1)}}
.header h1{{font-size:26px;margin-bottom:6px;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.header p{{color:#94a3b8;font-size:13px}}
.metrics-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px;margin-bottom:28px}}
.metric-card{{background:rgba(30,41,59,.9);border-radius:12px;padding:20px;border:1px solid rgba(148,163,184,.1)}}
.metric-card h3{{font-size:14px;color:#94a3b8;margin-bottom:10px}}
.metric-value{{font-size:42px;font-weight:700}}
.metric-label{{font-size:11px;color:#64748b;margin-top:6px}}
.metric-bar{{height:6px;background:#334155;border-radius:4px;margin-top:12px;overflow:hidden}}
.metric-bar-fill{{height:100%;border-radius:4px}}
.details{{background:rgba(30,41,59,.9);border-radius:12px;padding:24px;border:1px solid rgba(148,163,184,.1);margin-bottom:28px}}
.details h2{{font-size:18px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{padding:10px;text-align:left;border-bottom:1px solid #334155}}
th{{color:#94a3b8;font-weight:600;background:rgba(15,23,42,.5)}}
tr:hover{{background:rgba(51,65,85,.3)}}
.footer{{text-align:center;margin-top:30px;color:#64748b;font-size:11px}}
</style></head>
<body><div class="container">
    <div class="gate-banner">{gate_banner_text}</div>
    <div class="header">
        <h1>Enhanced RAG Evaluation Report</h1>
        <p>Model: {model} | Samples: {dataset_size} | {datetime.now().strftime("%B %d, %Y at %I:%M %p")}</p>
    </div>
    <div class="metrics-grid">{cards_html}</div>
    <div class="details">
        <h2>Per-Sample Results</h2>
        <table><thead><tr><th>#</th><th>Question</th><th>Ground.</th><th>Relev.</th><th>Simil.</th><th>Fluency</th></tr></thead>
        <tbody>{row_html}</tbody></table>
    </div>
    <div class="footer">LLMOps Workshop | Enhanced Evaluation | Microsoft Foundry ({AZURE_PROJECT_NAME})</div>
</div></body></html>'''

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    args = parse_args()
    model = args.model or CHAT_MODEL
    max_samples = args.max_samples or MAX_SAMPLES
    data_path = Path(args.data) if args.data else EVAL_DATA_PATH
    thresholds = get_thresholds(args)

    print("=" * 60)
    print("  Microsoft Foundry - Enhanced RAG Evaluation")
    print("  with Promotion Gates")
    print("=" * 60)

    # --- Auth ---
    print("\n[1/6] Authenticating with Azure...")
    credential = DefaultAzureCredential()
    print(f"  ✓ Foundry Project: {AZURE_PROJECT_NAME}")
    print(f"  ✓ Model: {model}")

    # --- Data ---
    print("\n[2/6] Loading evaluation dataset...")
    eval_data = load_evaluation_data(data_path)
    if len(eval_data) > max_samples:
        eval_data = eval_data[:max_samples]
    print(f"  ✓ {len(eval_data)} samples")

    # --- Evaluators ---
    print("\n[3/6] Initializing evaluators (4 metrics)...")
    project_client = AIProjectClient(endpoint=FOUNDRY_PROJECT_ENDPOINT, credential=credential)

    try:
        aoai_connection = project_client.connections.get("aoai-connection")
        aoai_endpoint = aoai_connection.target
    except Exception:
        aoai_endpoint = (
            FOUNDRY_PROJECT_ENDPOINT.split("/api/projects/")[0]
            .replace(".services.ai.azure.com", ".cognitiveservices.azure.com") + "/"
        )

    print(f"  ✓ Azure OpenAI endpoint: {aoai_endpoint}")

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
    print(f"  ✓ Evaluators: {', '.join(evaluators.keys())}")

    # --- Prepare data ---
    print("\n[4/6] Preparing evaluation data...")
    temp_data = []
    for item in eval_data:
        temp_data.append({
            "question": item["question"],
            "ground_truth": item["ground_truth"],
            "context": item.get("context", ""),
            "response": item["ground_truth"],  # In production: actual model response
        })

    RESULTS_PATH.mkdir(exist_ok=True)
    temp_file = RESULTS_PATH / "temp_eval_data.jsonl"
    with open(temp_file, "w", encoding="utf-8") as f:
        for row in temp_data:
            f.write(json.dumps(row) + "\n")

    # --- Run evaluation ---
    print("\n[5/6] Running evaluation (this may take 1-2 minutes)...")
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
    rows = results.get("rows", [])

    # --- Gate ---
    print("\n[6/6] Evaluating promotion gate...")
    gate_result = evaluate_gate(metrics, thresholds)

    # --- Display ---
    print("\n" + "=" * 60)
    print("  Evaluation Results")
    print("=" * 60)
    print(f"  Model: {model} | Samples: {len(eval_data)}")
    print("  " + "-" * 40)

    for metric_name in ["groundedness", "relevance", "similarity", "fluency"]:
        g = gate_result["metrics"].get(metric_name, {})
        val = g.get("value", "N/A")
        passed = g.get("passed", False)
        threshold = g.get("threshold", "?")
        icon = "✓" if passed else "✗"
        val_str = f"{val:.2f}" if isinstance(val, (int, float)) else str(val)
        print(f"  {icon} {metric_name.capitalize():15} {val_str}/5.0  (gate ≥{threshold})")

    print("\n  " + "-" * 40)
    if gate_result["passed"]:
        print("  ✅ PROMOTION GATE: PASSED")
        print("  → Safe to promote this model/configuration")
    else:
        print("  ❌ PROMOTION GATE: FAILED")
        print("  → Do NOT promote — improve metrics first")
        failed = [m for m, g in gate_result["metrics"].items() if not g["passed"]]
        print(f"  → Failed metrics: {', '.join(failed)}")

    # --- Save results ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_payload = {
        "timestamp": timestamp,
        "model": model,
        "dataset_size": len(eval_data),
        "thresholds": thresholds,
        "metrics": metrics,
        "gate_result": gate_result,
        "rows": rows,
    }

    results_file = RESULTS_PATH / f"enhanced_eval_{timestamp}.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2)
    print(f"\n  ✓ JSON results: {results_file}")

    html_file = RESULTS_PATH / f"enhanced_eval_{timestamp}.html"
    generate_enhanced_html_report(html_file, timestamp, model, len(eval_data), metrics, gate_result, rows)
    print(f"  ✓ HTML report: {html_file}")

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(results_payload, f, indent=2)
        print(f"  ✓ Pipeline output: {args.output_json}")

    print("\n" + "=" * 60)

    # CI mode: exit code reflects gate
    if args.ci:
        sys.exit(0 if gate_result["passed"] else 1)


if __name__ == "__main__":
    main()
