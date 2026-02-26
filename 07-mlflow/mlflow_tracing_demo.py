"""
LLMOps Workshop - MLflow Tracing & Prompt Versioning Demo
===========================================================
Shows how MLflow's GenAI features complement Microsoft Foundry for LLMOps:

1. MLflow Tracing: Capture full LLM call traces (prompts, completions, latency, tokens)
2. Prompt Versioning: Version-control prompt templates as MLflow LoggedModels
3. Application Versioning: Log RAG pipeline config as versioned artifacts

How MLflow fits alongside Foundry:
  - Foundry: Production inference, content safety, managed deployments
  - MLflow: Experiment tracking, prompt versioning, local tracing, offline evaluation
  - Together: Foundry for serving, MLflow for the development/iteration loop

Prerequisites:
  pip install mlflow>=2.18.0

Usage:
  python mlflow_tracing_demo.py
  # Then open MLflow UI: mlflow ui --port 5001

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
    from mlflow.models import set_model
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False
    print("ERROR: MLflow not installed. Run: pip install mlflow>=2.18.0")
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
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")

# Sample prompt templates to version
PROMPT_TEMPLATES = {
    "v1_basic": {
        "system": "You are a helpful customer support assistant for Wall-E Electronics.",
        "description": "Basic system prompt - no retrieval context integration"
    },
    "v2_rag": {
        "system": (
            "You are Wall-E, a friendly AI assistant for Wall-E Electronics.\n"
            "Answer customer questions based on the retrieved context below.\n"
            "If the context doesn't contain the answer, say so honestly.\n"
            "Keep responses under 200 words.\n\n"
            "# Retrieved Context:\n{context}"
        ),
        "description": "RAG-aware prompt with context injection"
    },
    "v3_structured": {
        "system": (
            "You are Wall-E, the official AI assistant for Wall-E Electronics.\n\n"
            "## Instructions\n"
            "1. Answer ONLY based on the retrieved context below\n"
            "2. If context is insufficient, say: 'I don't have enough information'\n"
            "3. Cite the source document when possible\n"
            "4. Keep responses under 150 words\n"
            "5. For pricing/availability, direct to wall-e.com\n\n"
            "## Retrieved Context\n{context}\n\n"
            "## Response Format\n"
            "Answer: [your answer]\n"
            "Source: [document name if available]"
        ),
        "description": "Structured prompt with citation and format instructions"
    },
}

# Sample questions for tracing demo
DEMO_QUESTIONS = [
    "What is the return policy for headphones?",
    "How do I reset my SmartWatch X200?",
    "What's the warranty on laptops?",
]


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


def demo_1_tracing(openai_client):
    """
    Demo 1: MLflow Tracing for LLM Calls
    ======================================
    Captures full traces of every LLM call including:
    - Input messages (system + user prompts)
    - Output completion
    - Token usage
    - Latency
    - Model name
    """
    print("\n" + "=" * 60)
    print("  Demo 1: MLflow Tracing")
    print("=" * 60)

    # Enable MLflow autologging for OpenAI - captures all calls automatically
    mlflow.openai.autolog(
        log_models=False,          # Don't log model artifacts (we use Foundry for deployment)
        log_input_examples=True,    # Capture input prompts
    )

    experiment_name = "llmops-tracing-demo"
    mlflow.set_experiment(experiment_name)
    print(f"  MLflow experiment: {experiment_name}")
    print(f"  Autologging enabled for OpenAI calls")

    with mlflow.start_run(run_name=f"rag-tracing-{datetime.now().strftime('%H%M%S')}"):
        # Log metadata
        mlflow.log_params({
            "foundry_project": AZURE_PROJECT_NAME,
            "chat_model": CHAT_MODEL,
            "prompt_version": "v2_rag",
        })

        system_prompt = PROMPT_TEMPLATES["v2_rag"]["system"].format(context="[Demo context]")

        for i, question in enumerate(DEMO_QUESTIONS, 1):
            print(f"\n  [{i}/{len(DEMO_QUESTIONS)}] Q: {question}")

            # This call is automatically traced by MLflow
            response = openai_client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                max_tokens=300,
                temperature=0.3,
            )

            answer = response.choices[0].message.content
            tokens = response.usage.total_tokens if response.usage else 0
            print(f"       A: {answer[:100]}...")
            print(f"       Tokens: {tokens}")

        print(f"\n  {len(DEMO_QUESTIONS)} calls traced")
        print(f"  View traces: mlflow ui --port 5001")


def demo_2_prompt_versioning(openai_client):
    """
    Demo 2: Prompt Versioning with MLflow
    =======================================
    Version-control prompt templates as MLflow artifacts.
    Each prompt version is logged with:
    - Template text
    - Description / changelog
    - Performance metrics (from evaluation)
    """
    print("\n" + "=" * 60)
    print("  Demo 2: Prompt Versioning")
    print("=" * 60)

    experiment_name = "llmops-prompt-versions"
    mlflow.set_experiment(experiment_name)

    for version_name, template in PROMPT_TEMPLATES.items():
        print(f"\n  Logging prompt: {version_name}")

        with mlflow.start_run(run_name=f"prompt-{version_name}"):
            # Log the prompt template as a parameter and artifact
            mlflow.log_params({
                "prompt_version": version_name,
                "description": template["description"],
                "model": CHAT_MODEL,
                "foundry_project": AZURE_PROJECT_NAME,
            })

            # Save prompt template as artifact
            prompt_dir = Path("mlflow_temp_prompts")
            prompt_dir.mkdir(exist_ok=True)
            prompt_file = prompt_dir / f"{version_name}.txt"
            with open(prompt_file, "w") as f:
                f.write(template["system"])
            mlflow.log_artifact(str(prompt_file), "prompts")

            # Run a sample call with this prompt to measure quality
            test_question = "What is the return policy for headphones?"
            system = template["system"].format(
                context="Return Policy: 30 days unopened, 14 days opened with 15% restocking fee."
            )

            response = openai_client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": test_question},
                ],
                max_tokens=300,
                temperature=0.3,
            )

            tokens = response.usage.total_tokens if response.usage else 0
            response_text = response.choices[0].message.content

            # Log metrics
            mlflow.log_metrics({
                "total_tokens": tokens,
                "response_length": len(response_text),
                "prompt_length": len(system),
            })

            print(f"    Template length: {len(template['system'])} chars")
            print(f"    Response tokens: {tokens}")
            print(f"    Logged to MLflow")

    # Cleanup temp files
    import shutil
    if Path("mlflow_temp_prompts").exists():
        shutil.rmtree("mlflow_temp_prompts")

    print(f"\n  {len(PROMPT_TEMPLATES)} prompt versions logged")
    print(f"  Compare prompts in MLflow UI: Experiments > llmops-prompt-versions")


def demo_3_application_versioning(openai_client):
    """
    Demo 3: Application Configuration Versioning
    ===============================================
    Log the full RAG pipeline configuration as a versioned MLflow run.
    Useful for tracking which combination of model + prompt + retrieval
    settings produced which quality metrics.
    """
    print("\n" + "=" * 60)
    print("  Demo 3: Application Config Versioning")
    print("=" * 60)

    experiment_name = "llmops-app-versions"
    mlflow.set_experiment(experiment_name)

    # Example configurations representing different iterations
    configs = [
        {
            "name": "v1.0-baseline",
            "model": "gpt-4o",
            "prompt_version": "v1_basic",
            "search_top_k": 3,
            "temperature": 0.7,
            "max_tokens": 500,
        },
        {
            "name": "v1.1-tuned",
            "model": "gpt-4o",
            "prompt_version": "v2_rag",
            "search_top_k": 5,
            "temperature": 0.3,
            "max_tokens": 300,
        },
        {
            "name": "v2.0-optimized",
            "model": "gpt-4o-mini",
            "prompt_version": "v3_structured",
            "search_top_k": 3,
            "temperature": 0.2,
            "max_tokens": 200,
        },
    ]

    for config in configs:
        print(f"\n  Logging config: {config['name']}")

        with mlflow.start_run(run_name=config["name"]):
            mlflow.log_params({
                "app_version": config["name"],
                "model": config["model"],
                "prompt_version": config["prompt_version"],
                "search_top_k": config["search_top_k"],
                "temperature": config["temperature"],
                "max_tokens": config["max_tokens"],
                "foundry_project": AZURE_PROJECT_NAME,
                "foundry_endpoint": FOUNDRY_PROJECT_ENDPOINT,
            })

            # Log full config as artifact
            config_dir = Path("mlflow_temp_configs")
            config_dir.mkdir(exist_ok=True)
            config_file = config_dir / f"{config['name']}.json"
            with open(config_file, "w") as f:
                json.dump(config, f, indent=2)
            mlflow.log_artifact(str(config_file), "configs")

            # Simulated metrics (in production, these come from evaluation)
            mlflow.log_metrics({
                "groundedness": 3.8 if "baseline" in config["name"] else 4.2 if "tuned" in config["name"] else 4.0,
                "relevance": 3.5 if "baseline" in config["name"] else 4.1 if "tuned" in config["name"] else 3.9,
                "fluency": 4.0 if "baseline" in config["name"] else 4.3 if "tuned" in config["name"] else 4.1,
                "tokens_per_call": 450 if "baseline" in config["name"] else 350 if "tuned" in config["name"] else 200,
            })

            print(f"    Logged config + metrics")

    # Cleanup
    import shutil
    if Path("mlflow_temp_configs").exists():
        shutil.rmtree("mlflow_temp_configs")

    print(f"\n  {len(configs)} app versions logged")
    print(f"  Compare versions in MLflow UI: Experiments > llmops-app-versions")
    print(f"  Use MLflow's comparison view to see which config performed best")


def main():
    print("=" * 60)
    print("  MLflow Tracing & Prompt Versioning Demo")
    print("  Microsoft Foundry + MLflow Integration")
    print("=" * 60)
    print(f"\n  Foundry: {AZURE_PROJECT_NAME}")
    print(f"  Model:   {CHAT_MODEL}")
    print(f"  MLflow:  {mlflow.__version__}")

    # Set up MLflow tracking (local by default)
    mlflow.set_tracking_uri("mlruns")
    print(f"  Tracking: ./mlruns (local)")

    # Connect to Foundry
    print("\n  Connecting to Microsoft Foundry...")
    openai_client, aoai_endpoint = setup_foundry_client()
    print(f"  Connected: {aoai_endpoint}")

    # Run demos
    demo_1_tracing(openai_client)
    demo_2_prompt_versioning(openai_client)
    demo_3_application_versioning(openai_client)

    print("\n" + "=" * 60)
    print("  All Demos Complete!")
    print("=" * 60)
    print(f"\n  View results:")
    print(f"    mlflow ui --port 5001")
    print(f"    Open http://localhost:5001")
    print(f"\n  Experiments created:")
    print(f"    1. llmops-tracing-demo       - Full call traces")
    print(f"    2. llmops-prompt-versions     - Prompt version comparison")
    print(f"    3. llmops-app-versions        - App config comparison")
    print(f"\n  How this complements Foundry:")
    print(f"    Foundry: Production inference, content safety, managed models")
    print(f"    MLflow:  Experiment tracking, prompt versions, development loop")
    print(f"    Together: Iterate with MLflow, promote through Foundry")
    print("=" * 60)


if __name__ == "__main__":
    main()
