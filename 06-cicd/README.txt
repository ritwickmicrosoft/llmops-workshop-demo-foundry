# =============================================================================
# LLMOps CI/CD Pipeline - Quick Reference
# =============================================================================
#
# This folder contains the Azure DevOps pipeline definition and gate logic
# for operationalizing your RAG chatbot on Microsoft Foundry.
#
# Files:
#   azure-pipelines.yml   - Full Azure DevOps YAML pipeline
#   promotion_gate.py     - Standalone gate checker (eval, safety, comparison)
#
# Pipeline Stages:
#   1. EvaluationGate       - 4-metric quality check (groundedness, relevance,
#                             similarity, fluency) with pass/fail thresholds
#   2. ContentSafetyGate    - Content safety tests (jailbreak, boundary, etc.)
#   3. ModelSwapGate        - Side-by-side comparison (triggered with [model-swap]
#                             in commit message or RUN_MODEL_SWAP=true)
#   4. Deploy               - Deploy to Azure (only on main, after all gates pass)
#
# Setup in Azure DevOps:
#   1. Create a Service Connection named 'llmops-service-connection'
#      pointing to your Azure subscription
#   2. Grant the service principal these RBAC roles:
#      - Cognitive Services OpenAI User (on foundry-llmops-canadaeast)
#      - Search Index Data Reader (on search-llmops-canadaeast)
#   3. Import the repo into Azure DevOps Repos (or use GitHub integration)
#   4. Create a new pipeline pointing to 06-cicd/azure-pipelines.yml
#
# Local Testing:
#   python 06-cicd/promotion_gate.py --check-eval --results 02-evaluation/eval_results/latest.json
#   python 06-cicd/promotion_gate.py --check-content-safety --results-dir 03-content-safety/test_results
#
# Microsoft Foundry: foundry-llmops-canadaeast / proj-llmops-demo
# =============================================================================
