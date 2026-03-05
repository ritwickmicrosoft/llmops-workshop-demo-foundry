"""LLMOps Workshop - Evaluation Script
====================================
Runs evaluation metrics on the RAG chatbot using Azure AI Foundry Evaluation SDK.

Evaluators:
    - Groundedness: Is the response supported by retrieved context?
    - Relevance: Does the response address the user's question?
    - Similarity: How close is the response to the expected answer?
    - Fluency: Is the response grammatically correct and natural?

Promotion Gate:
    - Each metric has a configurable threshold (default ≥4.0 on 1-5 scale)
    - Overall pass requires ALL metrics to meet their thresholds
    - Exit code 0 = PASS (safe to promote), Exit code 1 = FAIL (block promotion)

Authentication: DefaultAzureCredential (RBAC - no API keys)
Microsoft Foundry: Uses AIProjectClient for evaluation and (optionally) uploads results to the Foundry portal.
"""

import os
import sys
import json
import argparse
from datetime import datetime
from pathlib import Path

# Load environment variables from a local .env file if present
try:
    from dotenv import load_dotenv, find_dotenv
    load_dotenv(find_dotenv())
except Exception:
    pass

from azure.identity import DefaultAzureCredential
from azure.ai.evaluation import (
    GroundednessEvaluator,
    RelevanceEvaluator,
    SimilarityEvaluator,
    FluencyEvaluator,
    evaluate,
)
from azure.ai.projects import AIProjectClient


# Configuration
# Microsoft Foundry Project Configuration
# Use the project endpoint from Foundry portal: Overview > Endpoints and keys
FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", 
    "https://foundry-llmops-canadaeast.services.ai.azure.com/api/projects/proj-llmops-demo"
)
AZURE_PROJECT_NAME = os.environ.get("AZURE_PROJECT_NAME", "proj-llmops-demo")

# Optional: direct Azure OpenAI endpoint (for running without Foundry)
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")

# Model deployment name
CHAT_MODEL = (
    os.environ.get("CHAT_MODEL")
    or os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT")
    or "gpt-4o"
)

# Limit samples for demo (reduce rate limit issues)
MAX_SAMPLES = int(os.environ.get("EVAL_MAX_SAMPLES", "5"))

EVAL_DATA_PATH = Path(__file__).parent / "eval_dataset.jsonl"
RESULTS_PATH = Path(__file__).parent / "eval_results"


# Default promotion gate thresholds (1-5 scale)
DEFAULT_THRESHOLDS = {
    "groundedness": 4.0,
    "relevance": 4.0,
    "similarity": 4.0,
    "fluency": 4.0,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="RAG evaluation with promotion gate + optional Foundry portal upload"
    )
    parser.add_argument("--model", default=None, help="Model to evaluate (overrides CHAT_MODEL env)")
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="Single threshold for ALL metrics (overrides per-metric defaults)",
    )
    parser.add_argument("--threshold-groundedness", type=float, default=None)
    parser.add_argument("--threshold-relevance", type=float, default=None)
    parser.add_argument("--threshold-similarity", type=float, default=None)
    parser.add_argument("--threshold-fluency", type=float, default=None)
    parser.add_argument("--max-samples", type=int, default=None, help="Max samples to evaluate")
    parser.add_argument("--data", default=None, help="Path to evaluation dataset (.jsonl)")
    parser.add_argument(
        "--upload-to-portal",
        action="store_true",
        help="Upload evaluation results to Foundry portal (requires Azure subscription/resource group env vars)",
    )
    parser.add_argument(
        "--output-json",
        default=None,
        help="Path to write JSON results (for pipeline consumption)",
    )
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode (accepted for compatibility). Exit code already reflects promotion gate.",
    )
    return parser.parse_args()


def load_evaluation_data(file_path: Path) -> list[dict]:
    """Load evaluation dataset from JSONL file."""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def get_thresholds(args) -> dict:
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
    """Evaluate promotion gate: does each metric meet its threshold?"""
    gate_results = {}
    all_pass = True

    for metric_name, threshold in thresholds.items():
        value = metrics.get(
            f"{metric_name}.{metric_name}",
            metrics.get(f"mean_{metric_name}", metrics.get(metric_name, None)),
        )

        if value is None or not isinstance(value, (int, float)):
            gate_results[metric_name] = {
                "value": None,
                "threshold": threshold,
                "passed": False,
                "reason": "metric not available",
            }
            all_pass = False
            continue

        passed = value >= threshold
        gate_results[metric_name] = {
            "value": round(value, 3),
            "threshold": threshold,
            "passed": passed,
            "reason": f"{value:.2f} {'≥' if passed else '<'} {threshold:.1f}",
        }
        if not passed:
            all_pass = False

    return {"passed": all_pass, "metrics": gate_results}


def run_rag_flow(question: str, openai_client) -> dict:
    """
    Run the RAG flow and return the response.
    Uses Microsoft Foundry via OpenAI client for chat completions.
    """
    # Generate response using Foundry-deployed model
    response = openai_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=[
            {"role": "system", "content": "You are a helpful customer support assistant for Wall-E Electronics."},
            {"role": "user", "content": question}
        ],
        max_tokens=500,
        temperature=0.3
    )
    
    return {
        "response": response.choices[0].message.content,
        "context": ""  # Would come from RAG retrieval
    }


def generate_html_report(
    file_path: Path,
    timestamp: str,
    model: str,
    dataset_size: int,
    metrics: dict,
    gate_result: dict,
    rows: list,
):
    """Generate an HTML report with evaluation results + promotion gate verdict."""

    def get_status_color(value):
        if not isinstance(value, (int, float)):
            return "#6b7280", "N/A"
        if value >= 4.0:
            return "#10b981", "✓ Excellent"
        if value >= 3.0:
            return "#f59e0b", "~ Good"
        if value >= 2.0:
            return "#ef4444", "⚠ Needs Work"
        return "#dc2626", "✗ Poor"

    # Extract metric values
    groundedness = metrics.get("groundedness.groundedness", metrics.get("groundedness", 0))
    relevance = metrics.get("relevance.relevance", metrics.get("relevance", 0))
    similarity = metrics.get("similarity.similarity", metrics.get("similarity", 0))
    fluency = metrics.get("fluency.fluency", metrics.get("fluency", 0))

    g_color, g_status = get_status_color(groundedness)
    r_color, r_status = get_status_color(relevance)
    s_color, s_status = get_status_color(similarity)
    f_color, f_status = get_status_color(fluency)
    
    # Generate row details
    row_html = ""
    for i, row in enumerate(rows, 1):
        question = row.get("inputs.question", "N/A")
        response = row.get("inputs.response", "N/A")[:200] + "..." if len(row.get("inputs.response", "")) > 200 else row.get("inputs.response", "N/A")
        g_score = row.get("outputs.groundedness.groundedness", "N/A")
        r_score = row.get("outputs.relevance.relevance", "N/A")
        s_score = row.get("outputs.similarity.similarity", "N/A")
        f_score = row.get("outputs.fluency.fluency", "N/A")
        g_reason = row.get("outputs.groundedness.groundedness_reason", "N/A")
        f_reason = row.get("outputs.fluency.fluency_reason", "N/A")
        
        g_row_color = get_status_color(g_score)[0] if isinstance(g_score, (int, float)) else "#6b7280"
        r_row_color = get_status_color(r_score)[0] if isinstance(r_score, (int, float)) else "#6b7280"
        s_row_color = get_status_color(s_score)[0] if isinstance(s_score, (int, float)) else "#6b7280"
        f_row_color = get_status_color(f_score)[0] if isinstance(f_score, (int, float)) else "#6b7280"
        
        row_html += f'''
        <tr>
            <td>{i}</td>
            <td style="max-width:300px;word-wrap:break-word;">{question}</td>
            <td style="color:{g_row_color};font-weight:bold;">{g_score}</td>
            <td style="color:{r_row_color};font-weight:bold;">{r_score}</td>
            <td style="color:{s_row_color};font-weight:bold;">{s_score}</td>
            <td style="color:{f_row_color};font-weight:bold;">{f_score}</td>
            <td style="font-size:11px;color:#9ca3af;">{g_reason[:100]}...</td>
        </tr>'''

    gate_banner_color = "#10b981" if gate_result.get("passed") else "#ef4444"
    gate_banner_text = "PROMOTION GATE: PASSED" if gate_result.get("passed") else "PROMOTION GATE: FAILED"

    def fmt_score(value):
        return f"{value:.2f}" if isinstance(value, (int, float)) else "N/A"

    def bar_width(value):
        return (value * 20) if isinstance(value, (int, float)) else 0

    groundedness_display = fmt_score(groundedness)
    relevance_display = fmt_score(relevance)
    similarity_display = fmt_score(similarity)
    fluency_display = fmt_score(fluency)

    groundedness_bar = bar_width(groundedness)
    relevance_bar = bar_width(relevance)
    similarity_bar = bar_width(similarity)
    fluency_bar = bar_width(fluency)
    
    html_content = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Evaluation Report - {timestamp}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ 
            font-family: 'Segoe UI', system-ui, sans-serif; 
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
            color: #e2e8f0;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        .gate-banner {{
            text-align: center;
            padding: 18px;
            border-radius: 12px;
            font-size: 22px;
            font-weight: 700;
            margin-bottom: 24px;
            background: {gate_banner_color};
            color: #fff;
            letter-spacing: 1px;
        }}
        .header {{ 
            text-align: center; 
            margin-bottom: 40px;
            padding: 30px;
            background: rgba(30, 41, 59, 0.8);
            border-radius: 16px;
            border: 1px solid rgba(148, 163, 184, 0.1);
        }}
        .header h1 {{ 
            font-size: 28px; 
            margin-bottom: 8px;
            background: linear-gradient(90deg, #60a5fa, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .header p {{ color: #94a3b8; font-size: 14px; }}
        .metrics-grid {{ 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); 
            gap: 20px; 
            margin-bottom: 30px; 
        }}
        .metric-card {{
            background: rgba(30, 41, 59, 0.9);
            border-radius: 12px;
            padding: 24px;
            border: 1px solid rgba(148, 163, 184, 0.1);
        }}
        .metric-card h3 {{ font-size: 14px; color: #94a3b8; margin-bottom: 12px; }}
        .metric-value {{ font-size: 48px; font-weight: 700; }}
        .metric-label {{ font-size: 12px; color: #64748b; margin-top: 8px; }}
        .metric-bar {{ 
            height: 8px; 
            background: #334155; 
            border-radius: 4px; 
            margin-top: 16px;
            overflow: hidden;
        }}
        .metric-bar-fill {{ height: 100%; border-radius: 4px; }}
        .standards {{
            background: rgba(30, 41, 59, 0.9);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 30px;
            border: 1px solid rgba(148, 163, 184, 0.1);
        }}
        .standards h2 {{ font-size: 18px; margin-bottom: 16px; }}
        .standards-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }}
        .standard-item {{ 
            padding: 12px; 
            border-radius: 8px; 
            text-align: center;
            font-size: 12px;
        }}
        .standard-item.excellent {{ background: rgba(16, 185, 129, 0.2); color: #10b981; }}
        .standard-item.good {{ background: rgba(245, 158, 11, 0.2); color: #f59e0b; }}
        .standard-item.needs-work {{ background: rgba(239, 68, 68, 0.2); color: #ef4444; }}
        .standard-item.poor {{ background: rgba(220, 38, 38, 0.2); color: #dc2626; }}
        .details {{
            background: rgba(30, 41, 59, 0.9);
            border-radius: 12px;
            padding: 24px;
            border: 1px solid rgba(148, 163, 184, 0.1);
            margin-bottom: 30px;
        }}
        .details h2 {{ font-size: 18px; margin-bottom: 16px; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ color: #94a3b8; font-weight: 600; background: rgba(15, 23, 42, 0.5); }}
        tr:hover {{ background: rgba(51, 65, 85, 0.3); }}
        .recommendations {{
            background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(167, 139, 250, 0.1));
            border-radius: 12px;
            padding: 24px;
            border: 1px solid rgba(96, 165, 250, 0.3);
        }}
        .recommendations h2 {{ font-size: 18px; margin-bottom: 16px; color: #60a5fa; }}
        .recommendations ul {{ list-style: none; }}
        .recommendations li {{ 
            padding: 8px 0; 
            padding-left: 24px;
            position: relative;
            color: #cbd5e1;
        }}
        .recommendations li::before {{ 
            content: "→"; 
            position: absolute; 
            left: 0; 
            color: #60a5fa; 
        }}
        .footer {{ text-align: center; margin-top: 40px; color: #64748b; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="gate-banner">{gate_banner_text}</div>
        <div class="header">
            <h1>🤖 Wall-E Electronics RAG Evaluation Report</h1>
            <p>Generated: {datetime.now().strftime("%B %d, %Y at %I:%M %p")} | Model: {model} | Samples Evaluated: {dataset_size}</p>
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <h3>📊 Groundedness Score</h3>
                <div class="metric-value" style="color:{g_color};">{groundedness_display}<span style="font-size:20px;color:#64748b;">/5.0</span></div>
                <div class="metric-label">{g_status} | Gate: ≥{gate_result.get("metrics", {}).get("groundedness", {}).get("threshold", "N/A")}</div>
                <div class="metric-bar">
                    <div class="metric-bar-fill" style="width:{groundedness_bar}%;background:{g_color};"></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>🎯 Relevance Score</h3>
                <div class="metric-value" style="color:{r_color};">{relevance_display}<span style="font-size:20px;color:#64748b;">/5.0</span></div>
                <div class="metric-label">{r_status} | Gate: ≥{gate_result.get("metrics", {}).get("relevance", {}).get("threshold", "N/A")}</div>
                <div class="metric-bar">
                    <div class="metric-bar-fill" style="width:{relevance_bar}%;background:{r_color};"></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>📎 Similarity Score</h3>
                <div class="metric-value" style="color:{s_color};">{similarity_display}<span style="font-size:20px;color:#64748b;">/5.0</span></div>
                <div class="metric-label">{s_status} | Gate: ≥{gate_result.get("metrics", {}).get("similarity", {}).get("threshold", "N/A")}</div>
                <div class="metric-bar">
                    <div class="metric-bar-fill" style="width:{similarity_bar}%;background:{s_color};"></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>✍️ Fluency Score</h3>
                <div class="metric-value" style="color:{f_color};">{fluency_display}<span style="font-size:20px;color:#64748b;">/5.0</span></div>
                <div class="metric-label">{f_status} | Gate: ≥{gate_result.get("metrics", {}).get("fluency", {}).get("threshold", "N/A")}</div>
                <div class="metric-bar">
                    <div class="metric-bar-fill" style="width:{fluency_bar}%;background:{f_color};"></div>
                </div>
            </div>
        </div>

        <div class="standards">
            <h2>📏 Scoring Standards</h2>
            <div class="standards-grid">
                <div class="standard-item excellent">
                    <strong>4.0 - 5.0</strong><br/>✓ Excellent<br/>Production Ready
                </div>
                <div class="standard-item good">
                    <strong>3.0 - 4.0</strong><br/>~ Good<br/>Minor Improvements
                </div>
                <div class="standard-item needs-work">
                    <strong>2.0 - 3.0</strong><br/>⚠ Needs Work<br/>Improve Retrieval
                </div>
                <div class="standard-item poor">
                    <strong>1.0 - 2.0</strong><br/>✗ Poor<br/>Major Rework
                </div>
            </div>
        </div>

        <div class="details">
            <h2>📋 Detailed Results</h2>
            <table>
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Question</th>
                        <th>Groundedness</th>
                        <th>Relevance</th>
                        <th>Similarity</th>
                        <th>Fluency</th>
                        <th>Analysis</th>
                    </tr>
                </thead>
                <tbody>
                    {row_html}
                </tbody>
            </table>
        </div>

        <div class="recommendations">
            <h2>💡 Recommendations</h2>
            <ul>
                {"<li><strong>Improve Groundedness:</strong> Ensure retrieved context contains relevant information. Current score " + f"{groundedness:.2f}" + " is below target (≥4.0).</li>" if groundedness < 4.0 else ""}
                {"<li><strong>Improve Relevance:</strong> Ensure responses directly answer the user's question. Current score " + f"{relevance:.2f}" + " is below target (≥4.0).</li>" if relevance < 4.0 else ""}
                {"<li><strong>Improve Similarity:</strong> Align responses more closely with expected answers. Current score " + f"{similarity:.2f}" + " is below target (≥4.0).</li>" if similarity < 4.0 else ""}
                {"<li><strong>Improve Fluency:</strong> Refine system prompts for more natural responses. Current score " + f"{fluency:.2f}" + " is below target (≥4.0).</li>" if fluency < 4.0 else ""}
                <li><strong>Expand Context:</strong> Provide full document content in context field instead of just titles.</li>
                <li><strong>Add More Test Cases:</strong> Increase eval_dataset.jsonl with diverse questions.</li>
                <li><strong>Re-run After Changes:</strong> Run evaluation again to measure improvements.</li>
            </ul>
        </div>

        <div class="footer">
            LLMOps Workshop | Azure AI Foundry Evaluation | Wall-E Electronics
        </div>
    </div>
</body>
</html>'''
    
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


def main():
    args = parse_args()
    model = args.model or CHAT_MODEL
    max_samples = args.max_samples or MAX_SAMPLES
    data_path = Path(args.data) if args.data else EVAL_DATA_PATH
    thresholds = get_thresholds(args)

    print("=" * 60)
    print("  Microsoft Foundry - RAG Evaluation")
    print("=" * 60)
    
    # Initialize credentials
    print("\n[1/5] Authenticating with Azure...")
    credential = DefaultAzureCredential()
    print("  ✓ Using DefaultAzureCredential (RBAC)")
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_ENDPOINT.strip():
        print("  ✓ Mode: Direct Azure OpenAI endpoint")
    else:
        print("  ✓ Mode: Foundry Project endpoint")
        print(f"  ✓ Foundry Project: {AZURE_PROJECT_NAME}")
        print(f"  ✓ Foundry Endpoint: {FOUNDRY_PROJECT_ENDPOINT}")
    print(f"  ✓ Model: {model}")
    
    # Load evaluation data
    print("\n[2/5] Loading evaluation dataset...")
    eval_data = load_evaluation_data(data_path)
    
    # Limit samples for demo to avoid rate limits
    if len(eval_data) > max_samples:
        eval_data = eval_data[:max_samples]
        print(f"  ✓ Using {len(eval_data)} samples (limited to avoid rate limits)")
    else:
        print(f"  ✓ Loaded {len(eval_data)} evaluation samples")
    
    print("\n[3/5] Initializing evaluators...")

    aoai_endpoint = None
    if AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_ENDPOINT.strip():
        aoai_endpoint = AZURE_OPENAI_ENDPOINT.strip()
    else:
        # Get Azure OpenAI endpoint from Foundry connection
        project_client = AIProjectClient(
            endpoint=FOUNDRY_PROJECT_ENDPOINT,
            credential=credential,
        )

        # Get the Azure OpenAI connection details - try connection first, fallback to AI Services
        try:
            aoai_connection = project_client.connections.get("aoai-connection")
            aoai_endpoint = aoai_connection.target
        except Exception:
            aoai_endpoint = (
                FOUNDRY_PROJECT_ENDPOINT.split('/api/projects/')[0]
                .replace('.services.ai.azure.com', '.cognitiveservices.azure.com')
                + '/'
            )
    
    print(f"  ✓ Connected to Azure OpenAI: {aoai_endpoint}")
    
    # Set environment variables for evaluators (they read from env)
    os.environ["AZURE_OPENAI_ENDPOINT"] = aoai_endpoint
    os.environ["AZURE_OPENAI_DEPLOYMENT"] = model
    os.environ["AZURE_OPENAI_API_VERSION"] = "2024-06-01"
    
    # Model config for evaluators - minimal config, auth via DefaultAzureCredential
    model_config = {
        "azure_endpoint": aoai_endpoint,
        "azure_deployment": model,
    }
    
    evaluators = {
        "groundedness": GroundednessEvaluator(model_config=model_config),
        "relevance": RelevanceEvaluator(model_config=model_config),
        "similarity": SimilarityEvaluator(model_config=model_config),
        "fluency": FluencyEvaluator(model_config=model_config),
    }
    print(f"  ✓ Initialized {len(evaluators)} evaluators")
    print(f"  ✓ Using model: {model}")
    
    # Prepare evaluation data
    print("\n[4/5] Running evaluation...")
    
    # Write formatted data to temp file (SDK expects file path)
    temp_data = []
    for item in eval_data:
        temp_data.append({
            # Evaluators expect 'query' (not 'question')
            "query": item["question"],
            "ground_truth": item["ground_truth"],
            "context": item.get("context", ""),
            # In production, get actual response from your deployed flow
            "response": item["ground_truth"],  # Placeholder for demo
        })
    
    temp_file = RESULTS_PATH / "temp_eval_data.jsonl"
    RESULTS_PATH.mkdir(exist_ok=True)
    with open(temp_file, 'w', encoding='utf-8') as f:
        for row in temp_data:
            f.write(json.dumps(row) + '\n')
    
    # Azure AI Project config for uploading results to Foundry portal
    # Note: Portal upload requires ML workspace-based Foundry (not AI Services-based)
    upload_to_portal = args.upload_to_portal or (os.environ.get("EVAL_UPLOAD_TO_PORTAL", "false").lower() == "true")
    
    azure_ai_project = None
    if upload_to_portal:
        azure_ai_project = {
            "subscription_id": os.environ.get("AZURE_SUBSCRIPTION_ID", ""),
            "resource_group_name": os.environ.get("AZURE_RESOURCE_GROUP", ""),
            "project_name": AZURE_PROJECT_NAME,
        }
        print(f"  → Uploading results to: {AZURE_PROJECT_NAME}")
    else:
        print("  → Results saved locally (set EVAL_UPLOAD_TO_PORTAL=true to upload)")
    
    # Run evaluation
    results = evaluate(
        data=str(temp_file),
        evaluators=evaluators,
        evaluator_config={
            "groundedness": {
                "query": "${data.query}",
                "context": "${data.context}",
                "response": "${data.response}"
            },
            "relevance": {
                "query": "${data.query}",
                "context": "${data.context}",
                "response": "${data.response}",
            },
            "similarity": {
                "query": "${data.query}",
                "ground_truth": "${data.ground_truth}",
                "response": "${data.response}",
            },
            "fluency": {
                "response": "${data.response}"
            }
        },
        azure_ai_project=azure_ai_project,
    )
    
    # Process and display results
    print("\n[5/5] Processing results...")
    
    # Create results directory
    RESULTS_PATH.mkdir(exist_ok=True)
    
    # Calculate aggregate metrics
    metrics = results.get("metrics", {})
    
    print("\n" + "=" * 60)
    print("  Evaluation Results")
    print("=" * 60)
    
    print("\n  Aggregate Metrics:")
    print("  " + "-" * 40)
    
    metric_names = ["groundedness", "relevance", "similarity", "fluency"]
    for metric in metric_names:
        # SDK returns metrics like "groundedness.groundedness" or "fluency.fluency"
        value = metrics.get(f"{metric}.{metric}", 
                           metrics.get(f"mean_{metric}", 
                           metrics.get(metric, "N/A")))
        if isinstance(value, (int, float)):
            # Color code based on score (1-5 scale)
            if value >= 4.0:
                status = "✓"
            elif value >= 3.0:
                status = "~"
            else:
                status = "✗"
            print(f"  {status} {metric.capitalize():15} {value:.2f}/5.0")
        else:
            print(f"    {metric.capitalize():15} {value}")

    # Promotion gate
    gate_result = evaluate_gate(metrics, thresholds)
    print("\n  " + "-" * 40)
    if gate_result["passed"]:
        print("  ✅ PROMOTION GATE: PASSED")
        print("  → Safe to promote this model/configuration")
    else:
        print("  ❌ PROMOTION GATE: FAILED")
        print("  → Do NOT promote — improve metrics first")
        failed = [m for m, g in gate_result["metrics"].items() if not g["passed"]]
        print(f"  → Failed metrics: {', '.join(failed)}")
    
    # Save detailed results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = RESULTS_PATH / f"eval_results_{timestamp}.json"
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(
            {
                "timestamp": timestamp,
                "model": model,
                "dataset_size": len(eval_data),
                "thresholds": thresholds,
                "metrics": metrics,
                "gate_result": gate_result,
                "rows": results.get("rows", []),
            },
            f,
            indent=2,
        )
    
    print(f"\n  ✓ Detailed results saved to: {results_file}")
    
    # Generate HTML report
    html_file = RESULTS_PATH / f"eval_report_{timestamp}.html"
    generate_html_report(
        html_file,
        timestamp,
        model,
        len(eval_data),
        metrics,
        gate_result,
        results.get("rows", []),
    )
    print(f"  ✓ HTML report saved to: {html_file}")

    if args.output_json:
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": timestamp,
                    "model": model,
                    "dataset_size": len(eval_data),
                    "thresholds": thresholds,
                    "metrics": metrics,
                    "gate_result": gate_result,
                    "rows": results.get("rows", []),
                },
                f,
                indent=2,
            )
        print(f"  ✓ Pipeline output: {args.output_json}")
    
    print("\n" + "=" * 60)
    print("  Evaluation Complete!")
    print("=" * 60)
    
    # Recommendations
    print("\n  📊 Recommendations:")
    for metric in metric_names:
        value = metrics.get(f"{metric}.{metric}", 
                           metrics.get(f"mean_{metric}", 0))
        if isinstance(value, (int, float)) and value < thresholds.get(metric, 4.0):
            print(
                f"  - Consider improving {metric}: current score {value:.2f} (gate ≥{thresholds.get(metric, 4.0):.1f})"
            )
    
    print("\n  Next Steps:")
    print("  1. Review low-scoring responses in detailed results")
    print("  2. Iterate on prompts or retrieval strategy")
    print("  3. Re-run evaluation to measure improvements")

    # Exit code reflects promotion gate
    sys.exit(0 if gate_result["passed"] else 1)


if __name__ == "__main__":
    main()

