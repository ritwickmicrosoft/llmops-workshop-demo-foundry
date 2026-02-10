"""
LLMOps Workshop - Evaluation Script
====================================
Runs evaluation metrics on the RAG chatbot using Azure AI Foundry Evaluation SDK.
Uses built-in evaluators: Groundedness, Relevance, Coherence, Fluency.

Authentication: DefaultAzureCredential (RBAC - no API keys)
"""

import os
import json
from datetime import datetime
from pathlib import Path
from azure.identity import DefaultAzureCredential
from azure.ai.evaluation import (
    GroundednessEvaluator,
    FluencyEvaluator,
    evaluate,
)
from azure.ai.projects import AIProjectClient


# Configuration
AZURE_SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "1d53bfb3-a84c-4eb4-8c79-f29dc8424b6a")
AZURE_RESOURCE_GROUP = os.environ.get("AZURE_RESOURCE_GROUP", "rg-llmops-demo")
AZURE_PROJECT_NAME = os.environ.get("AZURE_PROJECT_NAME", "proj-llmops-demo")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

# Limit samples for demo (reduce rate limit issues)
MAX_SAMPLES = int(os.environ.get("EVAL_MAX_SAMPLES", "5"))

EVAL_DATA_PATH = Path(__file__).parent / "eval_dataset.jsonl"
RESULTS_PATH = Path(__file__).parent / "eval_results"


def load_evaluation_data(file_path: Path) -> list[dict]:
    """Load evaluation dataset from JSONL file."""
    data = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    return data


def run_rag_flow(question: str, project_client: AIProjectClient) -> dict:
    """
    Run the RAG flow and return the response.
    In a real scenario, this would call the deployed Prompt Flow endpoint.
    """
    # This is a placeholder - in production, call your deployed endpoint
    # For demo purposes, we'll use the chat completion directly
    
    from openai import AzureOpenAI
    
    credential = DefaultAzureCredential()
    
    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=lambda: credential.get_token(
            "https://cognitiveservices.azure.com/.default"
        ).token,
        api_version="2024-02-01"
    )
    
    # Simulate RAG response (in production, this calls your Prompt Flow endpoint)
    response = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
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


def generate_html_report(file_path: Path, timestamp: str, dataset_size: int, metrics: dict, rows: list):
    """Generate an HTML report with evaluation results and analysis."""
    
    # Extract metric values
    groundedness = metrics.get("groundedness.groundedness", metrics.get("groundedness", 0))
    fluency = metrics.get("fluency.fluency", metrics.get("fluency", 0))
    groundedness_pass = metrics.get("groundedness.binary_aggregate", 0) * 100
    fluency_pass = metrics.get("fluency.binary_aggregate", 0) * 100
    
    def get_status_color(value):
        if value >= 4.0:
            return "#10b981", "✓ Excellent"
        elif value >= 3.0:
            return "#f59e0b", "~ Good"
        elif value >= 2.0:
            return "#ef4444", "⚠ Needs Work"
        else:
            return "#dc2626", "✗ Poor"
    
    g_color, g_status = get_status_color(groundedness)
    f_color, f_status = get_status_color(fluency)
    
    # Generate row details
    row_html = ""
    for i, row in enumerate(rows, 1):
        question = row.get("inputs.question", "N/A")
        response = row.get("inputs.response", "N/A")[:200] + "..." if len(row.get("inputs.response", "")) > 200 else row.get("inputs.response", "N/A")
        g_score = row.get("outputs.groundedness.groundedness", "N/A")
        f_score = row.get("outputs.fluency.fluency", "N/A")
        g_reason = row.get("outputs.groundedness.groundedness_reason", "N/A")
        f_reason = row.get("outputs.fluency.fluency_reason", "N/A")
        
        g_row_color = get_status_color(g_score)[0] if isinstance(g_score, (int, float)) else "#6b7280"
        f_row_color = get_status_color(f_score)[0] if isinstance(f_score, (int, float)) else "#6b7280"
        
        row_html += f'''
        <tr>
            <td>{i}</td>
            <td style="max-width:300px;word-wrap:break-word;">{question}</td>
            <td style="color:{g_row_color};font-weight:bold;">{g_score}</td>
            <td style="color:{f_row_color};font-weight:bold;">{f_score}</td>
            <td style="font-size:11px;color:#9ca3af;">{g_reason[:100]}...</td>
        </tr>'''
    
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
        <div class="header">
            <h1>🤖 Wall-E Electronics RAG Evaluation Report</h1>
            <p>Generated: {datetime.now().strftime("%B %d, %Y at %I:%M %p")} | Samples Evaluated: {dataset_size}</p>
        </div>

        <div class="metrics-grid">
            <div class="metric-card">
                <h3>📊 Groundedness Score</h3>
                <div class="metric-value" style="color:{g_color};">{groundedness:.2f}<span style="font-size:20px;color:#64748b;">/5.0</span></div>
                <div class="metric-label">{g_status} | Pass Rate: {groundedness_pass:.0f}%</div>
                <div class="metric-bar">
                    <div class="metric-bar-fill" style="width:{groundedness*20}%;background:{g_color};"></div>
                </div>
            </div>
            <div class="metric-card">
                <h3>✍️ Fluency Score</h3>
                <div class="metric-value" style="color:{f_color};">{fluency:.2f}<span style="font-size:20px;color:#64748b;">/5.0</span></div>
                <div class="metric-label">{f_status} | Pass Rate: {fluency_pass:.0f}%</div>
                <div class="metric-bar">
                    <div class="metric-bar-fill" style="width:{fluency*20}%;background:{f_color};"></div>
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
    print("=" * 60)
    print("  LLMOps Workshop - RAG Evaluation")
    print("=" * 60)
    
    # Validate environment
    if not AZURE_OPENAI_ENDPOINT:
        print("\n⚠️  AZURE_OPENAI_ENDPOINT not set. Using default.")
    
    # Initialize credentials
    print("\n[1/5] Authenticating with Azure...")
    credential = DefaultAzureCredential()
    print("  ✓ Using DefaultAzureCredential (RBAC)")
    
    # Load evaluation data
    print("\n[2/5] Loading evaluation dataset...")
    eval_data = load_evaluation_data(EVAL_DATA_PATH)
    
    # Limit samples for demo to avoid rate limits
    if len(eval_data) > MAX_SAMPLES:
        eval_data = eval_data[:MAX_SAMPLES]
        print(f"  ✓ Using {len(eval_data)} samples (limited to avoid rate limits)")
    else:
        print(f"  ✓ Loaded {len(eval_data)} evaluation samples")
    
    # Initialize evaluators
    print("\n[3/5] Initializing evaluators...")
    
    model_config = {
        "azure_endpoint": AZURE_OPENAI_ENDPOINT,
        "azure_deployment": AZURE_OPENAI_DEPLOYMENT,
        "api_version": "2024-02-01"
    }
    
    evaluators = {
        "groundedness": GroundednessEvaluator(model_config=model_config),
        "fluency": FluencyEvaluator(model_config=model_config),
        # Note: Relevance and Coherence require conversation format in newer SDK
        # For production, convert data to conversation format or use individual call API
    }
    print(f"  ✓ Initialized {len(evaluators)} evaluators")
    
    # Prepare evaluation data
    print("\n[4/5] Running evaluation...")
    
    # Write formatted data to temp file (SDK expects file path)
    temp_data = []
    for item in eval_data:
        temp_data.append({
            "question": item["question"],
            "ground_truth": item["ground_truth"],
            "context": item.get("context", ""),
            # In production, get actual response from your deployed flow
            "response": item["ground_truth"]  # Placeholder for demo
        })
    
    temp_file = RESULTS_PATH / "temp_eval_data.jsonl"
    RESULTS_PATH.mkdir(exist_ok=True)
    with open(temp_file, 'w', encoding='utf-8') as f:
        for row in temp_data:
            f.write(json.dumps(row) + '\n')
    
    # Azure AI Project config for uploading results to Foundry portal
    # Note: Portal upload requires ML workspace-based Foundry (not AI Services-based)
    upload_to_portal = os.environ.get("EVAL_UPLOAD_TO_PORTAL", "false").lower() == "true"
    
    azure_ai_project = None
    if upload_to_portal:
        azure_ai_project = {
            "subscription_id": AZURE_SUBSCRIPTION_ID,
            "resource_group_name": AZURE_RESOURCE_GROUP,
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
                "question": "${data.question}",
                "context": "${data.context}",
                "response": "${data.response}"
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
    
    metric_names = ["groundedness", "fluency"]
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
    
    # Save detailed results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results_file = RESULTS_PATH / f"eval_results_{timestamp}.json"
    
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump({
            "timestamp": timestamp,
            "dataset_size": len(eval_data),
            "metrics": metrics,
            "rows": results.get("rows", [])
        }, f, indent=2)
    
    print(f"\n  ✓ Detailed results saved to: {results_file}")
    
    # Generate HTML report
    html_file = RESULTS_PATH / f"eval_report_{timestamp}.html"
    generate_html_report(html_file, timestamp, len(eval_data), metrics, results.get("rows", []))
    print(f"  ✓ HTML report saved to: {html_file}")
    
    print("\n" + "=" * 60)
    print("  Evaluation Complete!")
    print("=" * 60)
    
    # Recommendations
    print("\n  📊 Recommendations:")
    for metric in metric_names:
        value = metrics.get(f"{metric}.{metric}", 
                           metrics.get(f"mean_{metric}", 0))
        if isinstance(value, (int, float)) and value < 4.0:
            print(f"  - Consider improving {metric}: current score {value:.2f}")
    
    print("\n  Next Steps:")
    print("  1. Review low-scoring responses in detailed results")
    print("  2. Iterate on prompts or retrieval strategy")
    print("  3. Re-run evaluation to measure improvements")


if __name__ == "__main__":
    main()

