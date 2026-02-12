# ============================================================================
# LLMOps Workshop - Infrastructure Deployment Script
# ============================================================================
# This script deploys all Azure resources needed for the LLMOps workshop
# using RBAC authentication (no API keys)
# ============================================================================

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroupName = "rg-llmops-canadaeast",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "canadaeast",
    
    [Parameter(Mandatory=$false)]
    [string]$Environment = "dev",
    
    [Parameter(Mandatory=$false)]
    [switch]$SkipRoleAssignments
)

$ErrorActionPreference = "Stop"

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  LLMOps Workshop - Infrastructure Deploy  " -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan

# Check Azure CLI login
Write-Host "`n[1/5] Checking Azure CLI login..." -ForegroundColor Yellow
$account = az account show 2>$null | ConvertFrom-Json
if (-not $account) {
    Write-Host "Not logged in. Running 'az login'..." -ForegroundColor Yellow
    az login
    $account = az account show | ConvertFrom-Json
}
Write-Host "  Logged in as: $($account.user.name)" -ForegroundColor Green
Write-Host "  Subscription: $($account.name) ($($account.id))" -ForegroundColor Green

# Get current user's Object ID for RBAC
Write-Host "`n[2/5] Getting current user's Object ID..." -ForegroundColor Yellow
$currentUserObjectId = az ad signed-in-user show --query id -o tsv
if ($SkipRoleAssignments) {
    Write-Host "  Skipping role assignments (manual setup required)" -ForegroundColor Yellow
    $currentUserObjectId = ""
} else {
    Write-Host "  User Object ID: $currentUserObjectId" -ForegroundColor Green
}

# Register required resource providers
Write-Host "`n[3/5] Registering resource providers..." -ForegroundColor Yellow
$providers = @(
    "Microsoft.CognitiveServices",
    "Microsoft.Search",
    "Microsoft.MachineLearningServices",
    "Microsoft.Storage",
    "Microsoft.KeyVault",
    "Microsoft.OperationalInsights",
    "Microsoft.Insights"
)
foreach ($provider in $providers) {
    $state = az provider show --namespace $provider --query "registrationState" -o tsv 2>$null
    if ($state -ne "Registered") {
        Write-Host "  Registering $provider..." -ForegroundColor Yellow
        az provider register --namespace $provider
    } else {
        Write-Host "  $provider already registered" -ForegroundColor DarkGray
    }
}

# Deploy infrastructure
Write-Host "`n[4/5] Deploying infrastructure with Bicep..." -ForegroundColor Yellow
Write-Host "  Resource Group: $ResourceGroupName" -ForegroundColor Cyan
Write-Host "  Location: $Location" -ForegroundColor Cyan
Write-Host "  Environment: $Environment" -ForegroundColor Cyan

$deploymentParams = @(
    "--location", $Location,
    "--template-file", "$PSScriptRoot\main.bicep",
    "--parameters", "resourceGroupName=$ResourceGroupName",
    "--parameters", "location=$Location",
    "--parameters", "environment=$Environment"
)

if ($currentUserObjectId) {
    $deploymentParams += "--parameters", "principalId=$currentUserObjectId"
    $deploymentParams += "--parameters", "principalType=User"
}

$deployment = az deployment sub create @deploymentParams 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Deployment failed:" -ForegroundColor Red
    Write-Host $deployment
    exit 1
}

$outputs = $deployment | ConvertFrom-Json

Write-Host "`n[5/5] Deployment complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Resources Created:" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Resource Group:    $($outputs.properties.outputs.resourceGroupName.value)" -ForegroundColor White
Write-Host "  AI Foundry:        $($outputs.properties.outputs.foundryResourceName.value)" -ForegroundColor White
Write-Host "  Foundry Endpoint:  $($outputs.properties.outputs.foundryEndpoint.value)" -ForegroundColor White
Write-Host "  Project:           $($outputs.properties.outputs.projectName.value)" -ForegroundColor White
Write-Host "  OpenAI Endpoint:   $($outputs.properties.outputs.openAIEndpoint.value)" -ForegroundColor White
Write-Host "  Search Endpoint:   $($outputs.properties.outputs.searchEndpoint.value)" -ForegroundColor White
Write-Host "  Storage Account:   $($outputs.properties.outputs.storageAccountName.value)" -ForegroundColor White

# Set environment variables
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  Environment Variables (copy these):" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host @"
`$env:AZURE_SUBSCRIPTION_ID = "$($account.id)"
`$env:AZURE_RESOURCE_GROUP = "$($outputs.properties.outputs.resourceGroupName.value)"
`$env:AI_FOUNDRY_ENDPOINT = "$($outputs.properties.outputs.foundryEndpoint.value)"
`$env:AZURE_OPENAI_ENDPOINT = "$($outputs.properties.outputs.openAIEndpoint.value)"
`$env:AZURE_SEARCH_ENDPOINT = "$($outputs.properties.outputs.searchEndpoint.value)"
`$env:AZURE_STORAGE_ACCOUNT = "$($outputs.properties.outputs.storageAccountName.value)"
"@ -ForegroundColor Yellow

Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  Next Steps:" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  1. Models (gpt-4o, text-embedding-3-large) are auto-deployed!" -ForegroundColor White
Write-Host "  2. Run: python 01-rag-chatbot/create_search_index.py" -ForegroundColor White
Write-Host "  3. Run: python 04-frontend/app.py" -ForegroundColor White
Write-Host "`n  Portal: https://ai.azure.com" -ForegroundColor Cyan
