"""
LLMOps Workshop - MLflow Evaluate Demo
========================================
Demonstrates MLflow's built-in GenAI evaluation suites as a complement
to Azure AI Evaluation SDK (used in 02-evaluation/).

Key difference:
  - Azure AI Evaluation (02-evaluation/): Production-grade, integrates with
    Foundry portal, supports uploading results to Project
  - MLflow evaluate(): Developer-friendly, works offline, great for local
    iteration and experiment comparison

This demo shows:
  1. mlflow.evaluate() with LLM-as-judge metrics
  2. Custom evaluator functions
  3. Side-by-side comparison of evaluation approaches

Prerequisites:
  pip install mlflow>=2.18.0

Usage:
  python mlflow_eval_demo.py
  # View results: mlflow ui --port 5001

Authentication: DefaultAzureCredential (RBAC)
Microsoft Foundry: foundry-llmops-canadaeast / proj-llmops-demo
"""

import os
import json
from datetime import datetime
from pathlib import Path
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from openai import AzureOpenAI

try:
    import mlflow
    import pandas as pd
    MLFLOW_AVAILABLE = True
except ImportError:
    print("ERROR: Install required packages: pip install mlflow>=2.18.0 pandas")
    exit(1)


# =============================================================================
# Configuration - Microsoft Foundry (foundry-llmops-canadaeast)
# =============================================================================
FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT",
    "https://foundry-llmops-canadaeast.services.ai.azure.com/api/projects/proj-llmops-demo"
)
AZURE_PROJECT_NAME = os.environ.get("AZURE_PROJECT_NAME", "proj-llmops-demo")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o")

EVAL_DATA_PATH = Path(__file__).parent.parent / "02-evaluation" / "eval_dataset.jsonl"
RESULTS_PATH = Path(__file__).parent / "mlflow_eval_results"


def load_eval_data(file_path: Path, max_samples: int = 5) -> pd.DataFrame:
    """Load evaluation dataset and convert to DataFrame for MLflow."""
    data = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                data.append(json.loads(line))
    data = data[:max_samples]
    return pd.DataFrame(data)


def setup_foundry_client():
    """Initialize Foundry client and OpenAI client."""
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

    openai_client = AzureOpenAI(
        azure_endpoint=aoai_endpoint,
        azure_ad_token_provider=lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token,
        api_version="2024-02-01",
    )
    return openai_client, aoai_endpoint


def demo_1_mlflow_evaluate(openai_client, eval_df):
    """
    Demo 1: MLflow evaluate() with built-in GenAI metrics
    =======================================================
    Uses mlflow.evaluate() to run LLM-as-judge scoring on the RAG dataset.
    """
    print("\n" + "=" * 60)
    print("  Demo 1: MLflow evaluate() with GenAI Metrics")
    print("=" * 60)

    experiment_name = "llmops-mlflow-eval"
    mlflow.set_experiment(experiment_name)

    # Generate model responses for evaluation
    print("\n  Generating model responses...")
    responses = []
    for _, row in eval_df.iterrows():
        response = openai_client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[
                {"role": "system", "content": "You are a helpful customer support assistant for Wall-E Electronics."},
                {"role": "user", "content": row["question"]},
            ],
            max_tokens=300,
            temperature=0.3,
        )
        responses.append(response.choices[0].message.content)
        print(f"    ✓ {row['question'][:50]}...")

    eval_df["response"] = responses

    # Run MLflow evaluate with built-in metrics
    print("\n  Running MLflow evaluate()...")

    with mlflow.start_run(run_name=f"mlflow-eval-{datetime.now().strftime('%H%M%S')}"):
        mlflow.log_params({
            "model": CHAT_MODEL,
            "foundry_project": AZURE_PROJECT_NAME,
            "eval_samples": len(eval_df),
            "eval_method": "mlflow.evaluate()",
        })

        # Use MLflow's built-in LLM evaluation
        # This creates an LLM-as-judge using the same model
        results = mlflow.evaluate(
            data=eval_df,
            predictions="response",
            targets="ground_truth",
            model_type="question-answering",
            extra_metrics=[],  # Built-in QA metrics are included automatically
            evaluator_config={
                "col_mapping": {
                    "inputs": "question",
                    "context": "context",
                }
            },
        )

        # Display results
        print(f"\n  MLflow Evaluation Results:")
        print(f"  {'─' * 40}")
        if results.metrics:
            for metric_name, value in results.metrics.items():
                if isinstance(value, (int, float)):
                    print(f"    {metric_name}: {value:.4f}")
                else:
                    print(f"    {metric_name}: {value}")

        # Save the evaluation table
        RESULTS_PATH.mkdir(parents=True, exist_ok=True)
        if results.tables:
            for table_name, table_df in results.tables.items():
                table_path = RESULTS_PATH / f"mlflow_{table_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
                table_df.to_csv(table_path, index=False)
                print(f"\n    ✓ Table saved: {table_path}")

    print(f"\n  ✓ Results logged to MLflow experiment: {experiment_name}")


def demo_2_custom_evaluators(openai_client, eval_df):
    """
    Demo 2: Custom Evaluator Functions
    ====================================
    Shows how to create custom evaluation metrics beyond built-in ones.
    These can check domain-specific requirements.
    """
    print("\n" + "=" * 60)
    print("  Demo 2: Custom Evaluators")
    print("=" * 60)

    experiment_name = "llmops-custom-evaluators"
    mlflow.set_experiment(experiment_name)

    # --- Custom evaluator functions ---

    def response_length_check(response, **kwargs):
        """Check if response is within acceptable length."""
        word_count = len(response.split())
        return {
            "word_count": word_count,
            "length_ok": 1.0 if 10 <= word_count <= 200 else 0.0,
        }

    def contains_citation(response, context, **kwargs):
        """Check if response references the source context."""
        context_lower = context.lower() if context else ""
        response_lower = response.lower()
        # Check if any context keywords appear in response
        context_words = set(context_lower.split()) - {"the", "a", "an", "is", "of", "for", "and", "or", "in", "to"}
        matches = sum(1 for w in context_words if w in response_lower)
        score = min(matches / max(len(context_words), 1), 1.0)
        return {"citation_score": round(score, 2)}

    def no_hallucination_keywords(response, **kwargs):
        """Check response doesn't contain common hallucination indicators."""
        hallucination_phrases = [
            "i think", "i believe", "probably", "might be",
            "i'm not sure but", "let me guess",
        ]
        response_lower = response.lower()
        found = [p for p in hallucination_phrases if p in response_lower]
        return {
            "no_hallucination_phrases": 1.0 if not found else 0.0,
            "hallucination_phrases_found": len(found),
        }

    # Generate responses if not already present
    if "response" not in eval_df.columns:
        responses = []
        for _, row in eval_df.iterrows():
            resp = openai_client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": "You are a helpful customer support assistant for Wall-E Electronics."},
                    {"role": "user", "content": row["question"]},
                ],
                max_tokens=300,
                temperature=0.3,
            )
            responses.append(resp.choices[0].message.content)
        eval_df["response"] = responses

    # Run custom evaluators
    print("\n  Running custom evaluators on each sample...")

    with mlflow.start_run(run_name=f"custom-eval-{datetime.now().strftime('%H%M%S')}"):
        mlflow.log_params({
            "model": CHAT_MODEL,
            "evaluators": "response_length, citation, hallucination_check",
        })

        all_results = []
        for _, row in eval_df.iterrows():
            result = {}
            result.update(response_length_check(row["response"]))
            result.update(contains_citation(row["response"], row.get("context", "")))
            result.update(no_hallucination_keywords(row["response"]))
            result["question"] = row["question"]
            all_results.append(result)

        results_df = pd.DataFrame(all_results)

        # Log aggregate metrics
        for col in results_df.select_dtypes(include=["float64", "int64"]).columns:
            if col != "question":
                avg = results_df[col].mean()
                mlflow.log_metric(f"avg_{col}", avg)
                print(f"    avg_{col}: {avg:.2f}")

        # Save detailed results
        RESULTS_PATH.mkdir(parents=True, exist_ok=True)
        results_csv = RESULTS_PATH / f"custom_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        results_df.to_csv(results_csv, index=False)
        mlflow.log_artifact(str(results_csv))

    print(f"\n  ✓ Custom evaluator results logged to: {experiment_name}")


def demo_3_comparison_summary():
    """
    Demo 3: Side-by-side summary of Azure AI Evaluation vs MLflow Evaluate
    ========================================================================
    """
    print("\n" + "=" * 60)
    print("  Demo 3: Azure AI Evaluation vs MLflow — When to Use Which")
    print("=" * 60)

    comparison = """
  ┌────────────────────────┬──────────────────────────────┬──────────────────────────────┐
  │ Capability             │ Azure AI Evaluation          │ MLflow evaluate()            │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Built-in metrics       │ Groundedness, Relevance,     │ QA accuracy, toxicity,       │
  │                        │ Coherence, Fluency,          │ exact match, ROUGE,          │
  │                        │ Similarity                   │ latency, token count         │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ LLM-as-judge           │ ✓ (via Foundry models)       │ ✓ (via any OpenAI-compat)    │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Custom evaluators      │ ✓ (Python functions)         │ ✓ (Python functions)         │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Portal integration     │ ✓ Upload to Foundry portal   │ ✗ (MLflow UI only)           │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ CI/CD integration      │ ✓ (exit codes, JSON output)  │ ✓ (MLflow API, artifacts)    │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Prompt versioning      │ ✗                            │ ✓ (logged as artifacts)      │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Tracing                │ ✓ (via App Insights)         │ ✓ (MLflow Tracing)           │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Experiment tracking    │ ✗                            │ ✓ (runs, params, metrics)    │
  ├────────────────────────┼──────────────────────────────┼──────────────────────────────┤
  │ Best for               │ Production gates, CI/CD,     │ Development iteration,       │
  │                        │ compliance reporting         │ A/B testing, offline eval     │
  └────────────────────────┴──────────────────────────────┴──────────────────────────────┘

  Recommended Pattern:
    Development:  Use MLflow for rapid iteration (prompt tweaks, model comparison)
    Staging:      Run Azure AI Evaluation in pipeline with promotion gates
    Production:   Foundry tracing (App Insights) + periodic evaluation runs
"""
    print(comparison)


def main():
    print("=" * 60)
    print("  MLflow Evaluate Demo")
    print("  Azure AI Evaluation vs MLflow — Complementary Tools")
    print("=" * 60)
    print(f"\n  Foundry: {AZURE_PROJECT_NAME}")
    print(f"  Model:   {CHAT_MODEL}")
    print(f"  MLflow:  {mlflow.__version__}")

    mlflow.set_tracking_uri("mlruns")

    # Connect to Foundry
    print("\n  Connecting to Microsoft Foundry...")
    openai_client, aoai_endpoint = setup_foundry_client()
    print(f"  ✓ Connected: {aoai_endpoint}")

    # Load evaluation data
    eval_df = load_eval_data(EVAL_DATA_PATH, max_samples=5)
    print(f"  ✓ Loaded {len(eval_df)} evaluation samples")

    # Run demos
    demo_1_mlflow_evaluate(openai_client, eval_df)
    demo_2_custom_evaluators(openai_client, eval_df)
    demo_3_comparison_summary()

    print("\n" + "=" * 60)
    print("  MLflow Evaluate Demo Complete!")
    print("=" * 60)
    print(f"\n  View results:")
    print(f"    mlflow ui --port 5001")
    print(f"    Open http://localhost:5001")
    print(f"\n  Key takeaway:")
    print(f"    Use MLflow for development iteration + Azure AI Eval for production gates")
    print(f"    Both feed into the same operational workflow on Microsoft Foundry")
    print("=" * 60)


if __name__ == "__main__":
    main()
