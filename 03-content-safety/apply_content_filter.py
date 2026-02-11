"""
LLMOps Workshop - Apply Content Safety Filter
==============================================
Applies custom content filter configuration via Microsoft Foundry.

This script demonstrates how to view and configure content safety settings.
Content filters are managed through Microsoft Foundry Portal or Azure Content Safety API.

Authentication: DefaultAzureCredential (RBAC)
Microsoft Foundry: Uses Guardrails + controls in the portal
"""

import os
import json
from pathlib import Path
from azure.identity import DefaultAzureCredential


# Configuration - Microsoft Foundry
# Use the project endpoint from Foundry portal: Overview > Endpoints and keys
FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", 
    "https://foundry-llmops-canadaeast.services.ai.azure.com/api/projects/proj-llmops-demo"
)
FOUNDRY_PROJECT_NAME = os.environ.get("FOUNDRY_PROJECT_NAME", "proj-llmops-demo")
CHAT_MODEL = os.environ.get("CHAT_MODEL", "gpt-4o")

CONFIG_PATH = Path(__file__).parent / "content_filter_config.json"


def load_filter_config(config_path: Path) -> dict:
    """Load content filter configuration from JSON file."""
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    print("=" * 60)
    print("  Microsoft Foundry - Content Safety Configuration")
    print("=" * 60)
    
    # Initialize credentials
    print("\n[1/3] Authenticating with Azure...")
    credential = DefaultAzureCredential()
    print("  Using DefaultAzureCredential (RBAC)")
    print(f"  Foundry Project: {FOUNDRY_PROJECT_NAME}")
    print(f"  Foundry Endpoint: {FOUNDRY_PROJECT_ENDPOINT}")
    
    # Load filter configuration
    print("\n[2/3] Loading content filter configuration...")
    filter_config = load_filter_config(CONFIG_PATH)
    print(f"  Filter name: {filter_config['name']}")
    print(f"  Base policy: {filter_config['basePolicyName']}")
    
    # Display filter settings
    print("\n  Input Filters:")
    for key, value in filter_config['inputFilters'].items():
        if value.get('filterEnabled'):
            threshold = value.get('severityThreshold', 'N/A')
            print(f"    - {key}: {threshold}")
    
    print("\n  Output Filters:")
    for key, value in filter_config['outputFilters'].items():
        if value.get('filterEnabled'):
            threshold = value.get('severityThreshold', 'Enabled')
            print(f"    - {key}: {threshold}")
    
    # Guide for applying in Microsoft Foundry
    print("\n[3/3] Content Filter Application Guide")
    print("\n" + "=" * 60)
    print("  Microsoft Foundry Content Safety")
    print("=" * 60)
    print(f"""
  To apply content safety in Microsoft Foundry:
  
  1. Open Microsoft Foundry Portal: https://ai.azure.com
  
  2. Navigate to your project: {FOUNDRY_PROJECT_NAME}
  
  3. Go to 'Guardrails + controls' under 'Protect and govern'
  
  4. Configure Content Filters:
     - Click 'Content filters'
     - Create a new filter with the settings shown above
     - Apply to your model deployment: {CHAT_MODEL}
  
  5. Enable Risks + alerts for monitoring
  
  Alternative: Use Azure AI Content Safety API
  - Install: pip install azure-ai-contentsafety
  - Use ContentSafetyClient for real-time content analysis
  
  For programmatic filtering during inference:
  - Use the analyze_text() method before sending to model
  - Block or modify content based on severity thresholds
""")
    
    print("  Content filter configuration ready for application!")
    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
