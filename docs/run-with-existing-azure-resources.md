# Run This Workshop Using Existing Azure Resources (No Bicep)

This guide is for customers who want to run the workshop **in their own Azure environment** using **existing** Azure resources (or resources created by their standard process), and **do not want to use the `infra/` Bicep templates**.

## What you need (at a minimum)

You can skip Bicep **only if these already exist** and you have access:

- **Azure AI Foundry Project** (you will copy its **Project endpoint**)
- Model deployments available to your Foundry project (either of these patterns):
  - **Pattern A (AI Services-hosted):** deploy `gpt-4o` and `text-embedding-3-large` to the AI Services (Foundry) resource
  - **Pattern B (separate Azure OpenAI):** deploy those models to an Azure OpenAI resource and add a Foundry connection named `aoai-connection`
- **Azure AI Search** service
- (Recommended) **Application Insights** if you want tracing/telemetry

## Choose a scenario (both are supported)

### Scenario A — Run locally only

Use this if the customer just wants to run the workshop scripts + local Flask app on their machine.

You will authenticate as your signed-in identity via `az login` (through `DefaultAzureCredential`).

### Scenario B — Deploy the frontend to Azure (App Service)

Use this if the customer wants a hosted chatbot endpoint.

You will:
- deploy `04-frontend/app.py` to App Service (or their standard hosting)
- enable **Managed Identity** on the app
- grant RBAC roles to that Managed Identity (so no secrets/API keys)

## RBAC permissions checklist

This repo is designed to run **without API keys** using `DefaultAzureCredential` (locally) and Managed Identity (when deployed).

Ensure the identity you will run with (your user, service principal, or managed identity) has:

- On **Azure AI Foundry** resource:
  - `Cognitive Services User` (minimum)
- On **Azure OpenAI** resource:
  - `Cognitive Services OpenAI User` (minimum)
- On **Azure AI Search** resource:
  - `Search Service Contributor` (to create/update the index)
  - `Search Index Data Contributor` (to upload documents)

Additional requirements for **Scenario B (App Service)**:

- The **App Service Managed Identity** needs:
  - On **Azure AI Foundry** resource: `Cognitive Services User`
  - On **Azure OpenAI** resource: `Cognitive Services OpenAI User`
  - On **Azure AI Search** resource: `Search Index Data Reader` (minimum for query-time) or `Search Index Data Contributor` (if you want the app to write)
- If using tracing, the app also needs permission to write telemetry (typically handled by the App Insights connection string).

If your org uses stricter separation (create vs data ops), assign roles accordingly.

## Step 1 — Set up Python

From the repo root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
az login
```

If you have multiple subscriptions:

```powershell
az account set --subscription "<subscription-name-or-id>"
```

## Step 2 — Populate `.env`

Copy the template and fill it with **your** endpoints/names:

```powershell
Copy-Item .env.example .env
```

Minimum values to set in `.env`:

- `FOUNDRY_PROJECT_ENDPOINT`  
  Copy from Foundry portal: **Project → Overview → Endpoints and keys → Project endpoint**
- `FOUNDRY_PROJECT_NAME` (optional; mostly display)
- `AZURE_SEARCH_ENDPOINT` (example: `https://<search>.search.windows.net`)
- `AZURE_SEARCH_INDEX_NAME` (default: `walle-products`)
- `CHAT_MODEL` (default: `gpt-4o`)
- `EMBEDDING_MODEL` (default: `text-embedding-3-large`)

Optional (only if you use evaluation upload to the portal):

- `AZURE_SUBSCRIPTION_ID`
- `AZURE_RESOURCE_GROUP`

## Step 3 — Create the search index and load documents

This reads the `data/` folder, creates/updates the index schema, embeds the docs, and uploads them to AI Search:

```powershell
python 01-rag-chatbot/create_search_index.py
```

## Step 4 — Run the chatbot locally

```powershell
python 04-frontend/app.py
```

Then open `http://localhost:5000`.

## Scenario B — Deploy the chatbot to Azure App Service (optional)

This repo includes a helper script ([04-frontend/deploy-to-azure.ps1](../04-frontend/deploy-to-azure.ps1)) that can deploy App Service.
If the customer uses a different deployment standard (Terraform, internal pipelines, etc.), the key is still the same: **set the app settings** and **assign RBAC** to the managed identity.

### 1) Required App Settings (environment variables)

Set these as App Service application settings:

- `FOUNDRY_PROJECT_ENDPOINT`
- `FOUNDRY_PROJECT_NAME`
- `AZURE_SEARCH_ENDPOINT`
- `AZURE_SEARCH_INDEX_NAME`
- `CHAT_MODEL`
- `EMBEDDING_MODEL`

Optional (only if you enable tracing):

- `APPLICATIONINSIGHTS_CONNECTION_STRING`

### 2) Assign RBAC to the App Service Managed Identity

At minimum, grant the managed identity:

- `Cognitive Services User` on the Foundry resource
- `Cognitive Services OpenAI User` on the Azure OpenAI resource
- `Search Index Data Reader` on the Search service

### 3) Validate

- Browse the app and confirm it can answer a question
- If it fails with `401/403`, re-check role assignments and subscription context

## Step 5 — Run the quality evaluation gate

```powershell
python 02-evaluation/run_evaluation.py
```

Notes:
- The script exits `0` for PASS and `1` for FAIL (promotion gate).
- Use `--max-samples` to control cost/latency.

## Step 6 — Run the content safety test suite

```powershell
python 03-content-safety/test_content_safety.py
```

This generates HTML + JSON reports under `03-content-safety/test_results/`.

## Optional — Model swap evaluation

```powershell
python 05-model-swap/model_swap_eval.py
```

## Optional — MLflow demos

```powershell
python 07-mlflow/mlflow_tracing_demo.py
python 07-mlflow/mlflow_eval_demo.py
```

## Troubleshooting

- **Auth errors / 401 / forbidden**: confirm you ran `az login` and the identity has the RBAC roles listed above.
- **Search index create fails**: ensure `Search Service Contributor` is assigned on the Search resource.
- **Embedding or chat calls fail**: confirm your Foundry project has access to the required model deployments, and your identity has `Cognitive Services OpenAI User` on the Azure OpenAI resource.
- **Wrong subscription**: run `az account show` and `az account set`.
