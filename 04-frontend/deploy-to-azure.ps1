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

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Deploy Chatbot to Azure App Service" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Validate inputs
if (-not $ResourceGroup) {
    Write-Host "❌ Resource group not specified." -ForegroundColor Red
    Write-Host "   Set `$env:AZURE_RESOURCE_GROUP or use -ResourceGroup parameter" -ForegroundColor Yellow
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

# Create startup command
@"
gunicorn --bind=0.0.0.0:8000 app:app
"@ | Out-File -FilePath "$deployPath\startup.txt" -Encoding utf8

# Deploy
Push-Location $deployPath
az webapp up --name $AppName --resource-group $ResourceGroup
Pop-Location

# Cleanup
Remove-Item $deployPath -Recurse -Force

Write-Host "`n============================================" -ForegroundColor Green
Write-Host "  ✓ Deployment Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host "`n  Web App URL: https://${AppName}.azurewebsites.net" -ForegroundColor Cyan
Write-Host "`n  Managed Identity: $identity" -ForegroundColor White
Write-Host "`n  ⚠️  IMPORTANT: Grant RBAC roles to the Managed Identity:" -ForegroundColor Yellow

Write-Host @"

  # Grant Cognitive Services OpenAI User role
  az role assignment create \`
    --assignee $identity \`
    --role "Cognitive Services OpenAI User" \`
    --scope /subscriptions/`$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$ResourceGroup

  # Grant Search Index Data Reader role  
  az role assignment create \`
    --assignee $identity \`
    --role "Search Index Data Reader" \`
    --scope /subscriptions/`$env:AZURE_SUBSCRIPTION_ID/resourceGroups/$ResourceGroup

"@ -ForegroundColor White

