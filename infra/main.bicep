// ============================================================================
// LLMOps Workshop Infrastructure - Azure AI Foundry with RBAC
// ============================================================================
// Deploys: AI Foundry Hub, Project, Azure OpenAI, AI Search, Storage
// Authentication: Managed Identity + RBAC (no API keys)
// ============================================================================

targetScope = 'subscription'

// Parameters
@description('Name of the resource group')
param resourceGroupName string = 'rg-llmops-canadaeast'

@description('Azure region for all resources')
@allowed([
  'canadaeast'
  'canadacentral'
  'eastus'
  'eastus2'
  'westus'
  'westus3'
  'northcentralus'
  'southcentralus'
  'swedencentral'
  'westeurope'
  'francecentral'
  'uksouth'
  'australiaeast'
  'japaneast'
])
param location string = 'canadaeast'

@description('Base name for all resources')
param baseName string = 'llmops'

@description('Environment suffix')
@allowed(['dev', 'test', 'prod'])
param environment string = 'dev'

@description('Object ID of the user or service principal to grant access')
param principalId string = ''

@description('Principal type')
@allowed(['User', 'ServicePrincipal', 'Group'])
param principalType string = 'User'

// Variables
var uniqueSuffix = uniqueString(resourceGroupName, subscription().subscriptionId)
var resourceNamePrefix = '${baseName}-${environment}'

// Resource Group
resource rg 'Microsoft.Resources/resourceGroups@2023-07-01' = {
  name: resourceGroupName
  location: location
  tags: {
    Environment: environment
    Project: 'LLMOps Workshop'
    Purpose: 'Demo'
  }
}

// Deploy Core Infrastructure
module coreInfra 'modules/core.bicep' = {
  scope: rg
  name: 'core-infrastructure'
  params: {
    location: location
    resourceNamePrefix: resourceNamePrefix
    uniqueSuffix: uniqueSuffix
    principalId: principalId
    principalType: principalType
  }
}

// Outputs
output resourceGroupName string = rg.name
output foundryResourceName string = coreInfra.outputs.foundryResourceName
output foundryEndpoint string = coreInfra.outputs.foundryEndpoint
output projectName string = coreInfra.outputs.projectName
output openAIEndpoint string = coreInfra.outputs.openAIEndpoint
output searchEndpoint string = coreInfra.outputs.searchEndpoint
output storageAccountName string = coreInfra.outputs.storageAccountName
