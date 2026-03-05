# ============================================================================
# Deploy Frontend to Azure App Service
# ============================================================================
# This script deploys the chatbot frontend to Azure App Service with
# Managed Identity for RBAC authentication to Azure AI Foundry services.
# ============================================================================

param(
    [Parameter(Mandatory=$false)]
    [string]$AppName = "walle-chatbot-$((Get-Random -Maximum 9999))",
    
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = $env:AZURE_RESOURCE_GROUP,
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "canadaeast",
    
    [Parameter(Mandatory=$false)]
    [string]$PromptFlowEndpoint = $env:AZURE_PROMPTFLOW_ENDPOINT,
    
    [Parameter(Mandatory=$false)]
    [string]$OpenAIEndpoint = $env:AZURE_OPENAI_ENDPOINT,
    
    [Parameter(Mandatory=$false)]
    [string]$SearchEndpoint = $env:AZURE_SEARCH_ENDPOINT
)

$ErrorActionPreference = "Stop"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Key
    )

    if (-not (Test-Path $Path)) {
        return $null
    }

    foreach ($line in Get-Content -Path $Path -ErrorAction SilentlyContinue) {
        $trimmed = ("$line").Trim()
        if (-not $trimmed) { continue }
        if ($trimmed.StartsWith('#')) { continue }

        if ($trimmed -match "^\s*${Key}\s*=\s*(.*)\s*$") {
            $value = $Matches[1].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                if ($value.Length -ge 2) {
                    $value = $value.Substring(1, $value.Length - 2)
                }
            }
            return $value
        }
    }

    return $null
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$dotEnvPath = Join-Path $repoRoot ".env"

# Fill missing values from .env when available
if (-not $ResourceGroup) { $ResourceGroup = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_RESOURCE_GROUP" }
if (-not $PromptFlowEndpoint) { $PromptFlowEndpoint = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_PROMPTFLOW_ENDPOINT" }
if (-not $OpenAIEndpoint) { $OpenAIEndpoint = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_OPENAI_ENDPOINT" }
if (-not $SearchEndpoint) { $SearchEndpoint = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_SEARCH_ENDPOINT" }

$searchIndexName = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_SEARCH_INDEX_NAME"
$chatDeployment = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_OPENAI_CHAT_DEPLOYMENT"
$embeddingDeployment = Get-DotEnvValue -Path $dotEnvPath -Key "AZURE_OPENAI_EMBEDDING_DEPLOYMENT"
$foundryProjectEndpoint = Get-DotEnvValue -Path $dotEnvPath -Key "FOUNDRY_PROJECT_ENDPOINT"
$foundryProjectName = Get-DotEnvValue -Path $dotEnvPath -Key "FOUNDRY_PROJECT_NAME"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Deploy Chatbot to Azure App Service" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Validate inputs
if (-not $ResourceGroup) {
    Write-Host "❌ Resource group not specified." -ForegroundColor Red
    Write-Host "   Set `$env:AZURE_RESOURCE_GROUP or use -ResourceGroup parameter" -ForegroundColor Yellow
    if (Test-Path $dotEnvPath) {
        Write-Host "   Also supported: set AZURE_RESOURCE_GROUP in $dotEnvPath" -ForegroundColor Yellow
    }
    exit 1
}

Write-Host "`n[1/5] Creating App Service Plan..." -ForegroundColor Yellow
az appservice plan create `
    --name "${AppName}-plan" `
    --resource-group $ResourceGroup `
    --location $Location `
    --sku B1 `
    --is-linux

Write-Host "`n[2/5] Creating Web App with Python 3.11..." -ForegroundColor Yellow
az webapp create `
    --name $AppName `
    --resource-group $ResourceGroup `
    --plan "${AppName}-plan" `
    --runtime "PYTHON:3.11"

Write-Host "`n[3/5] Enabling Managed Identity..." -ForegroundColor Yellow
$identity = az webapp identity assign `
    --name $AppName `
    --resource-group $ResourceGroup `
    --query principalId -o tsv

Write-Host "  Managed Identity Principal ID: $identity" -ForegroundColor Green

Write-Host "`n[4/5] Configuring App Settings..." -ForegroundColor Yellow
$settings = @()
if ($PromptFlowEndpoint) {
    $settings += "AZURE_PROMPTFLOW_ENDPOINT=$PromptFlowEndpoint"
}
if ($OpenAIEndpoint) {
    $settings += "AZURE_OPENAI_ENDPOINT=$OpenAIEndpoint"
}
if ($SearchEndpoint) {
    $settings += "AZURE_SEARCH_ENDPOINT=$SearchEndpoint"
}

# App runtime config
if ($searchIndexName) {
    $settings += "AZURE_SEARCH_INDEX_NAME=$searchIndexName"
}
if ($chatDeployment) {
    $settings += "AZURE_OPENAI_CHAT_DEPLOYMENT=$chatDeployment"
}
if ($embeddingDeployment) {
    $settings += "AZURE_OPENAI_EMBEDDING_DEPLOYMENT=$embeddingDeployment"
}
if ($foundryProjectEndpoint) {
    $settings += "FOUNDRY_PROJECT_ENDPOINT=$foundryProjectEndpoint"
}
if ($foundryProjectName) {
    $settings += "FOUNDRY_PROJECT_NAME=$foundryProjectName"
}

# Ensure the platform routes traffic to the right port
$settings += "WEBSITES_PORT=8000"

# Ensure dependencies are installed during zip deploy (Oryx build)
$settings += "SCM_DO_BUILD_DURING_DEPLOYMENT=true"
$settings += "ENABLE_ORYX_BUILD=true"

if ($settings.Count -gt 0) {
    az webapp config appsettings set `
        --name $AppName `
        --resource-group $ResourceGroup `
        --settings @settings
}

Write-Host "`n[5/5] Deploying Application Code..." -ForegroundColor Yellow
# Create deployment package
$deployPath = "$PSScriptRoot\deploy-package"
if (Test-Path $deployPath) { Remove-Item $deployPath -Recurse -Force }
New-Item -ItemType Directory -Path $deployPath -Force | Out-Null

# Copy files
Copy-Item "$PSScriptRoot\app.py" $deployPath
Copy-Item "$PSScriptRoot\index.html" $deployPath
Copy-Item "$PSScriptRoot\requirements.txt" $deployPath

# Trigger build actions (pip install -r requirements.txt) during ZipDeploy
"[config]`nSCM_DO_BUILD_DURING_DEPLOYMENT=true`n" | Out-File -FilePath "$deployPath\.deployment" -Encoding ascii

# Deploy via zipdeploy (more predictable than `az webapp up`)
$zipPath = Join-Path $PSScriptRoot "deploy-package.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }

# NOTE: Wildcards don't include dotfiles like `.deployment`, so list paths explicitly.
$zipPaths = @(
    (Join-Path $deployPath 'app.py'),
    (Join-Path $deployPath 'index.html'),
    (Join-Path $deployPath 'requirements.txt'),
    (Join-Path $deployPath '.deployment')
)
Compress-Archive -Path $zipPaths -DestinationPath $zipPath -Force

az webapp deployment source config-zip --name $AppName --resource-group $ResourceGroup --src $zipPath

# Ensure the Linux app uses our startup command (avoid BOM/encoding issues)
az webapp config set --name $AppName --resource-group $ResourceGroup --startup-file "python -m gunicorn --bind=0.0.0.0:8000 app:app"

# Restart to pick up new settings/deployment
az webapp restart --name $AppName --resource-group $ResourceGroup

# Cleanup
Remove-Item $deployPath -Recurse -Force
Remove-Item $zipPath -Force

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  ✓ Deployment Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "`n  Web App URL: https://${AppName}.azurewebsites.net" -ForegroundColor Cyan
Write-Host "`n  Managed Identity: $identity" -ForegroundColor White
Write-Host "`n  ⚠️  IMPORTANT: Grant RBAC roles to the Managed Identity:" -ForegroundColor Yellow

$cmd1 = "az role assignment create --assignee $identity --role `"Cognitive Services OpenAI User`" --scope /subscriptions/$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$ResourceGroup"
$cmd2 = "az role assignment create --assignee $identity --role `"Search Index Data Reader`" --scope /subscriptions/$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$ResourceGroup"

Write-Host "" -ForegroundColor White
Write-Host "  # Grant Cognitive Services OpenAI User role" -ForegroundColor White
Write-Host "  $cmd1" -ForegroundColor White
Write-Host "" -ForegroundColor White
Write-Host "  # Grant Search Index Data Reader role" -ForegroundColor White
Write-Host "  $cmd2" -ForegroundColor White

