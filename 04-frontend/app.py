"""
LLMOps Workshop - Azure AI Foundry Backend
============================================
Backend for the RAG chatbot using Azure AI Foundry services.

This version uses:
- Azure AI Foundry Hub & Project for centralized management
- Hub Connections for Azure OpenAI and AI Search (RBAC-based)
- get_openai_client() from AIProjectClient when available

Authentication uses RBAC (Managed Identity) - no API keys required.

Run: python app.py
Access: http://localhost:5000
"""

import os
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential
from azure.ai.projects import AIProjectClient
from openai import AzureOpenAI

# Tracing imports
try:
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.instrumentation.flask import FlaskInstrumentor
    from opentelemetry.instrumentation.openai_v2 import OpenAIInstrumentor
    import os
    # Enable content capture via environment variable
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "true"
    TRACING_AVAILABLE = True
except ImportError:
    TRACING_AVAILABLE = False
    print("⚠ Tracing packages not installed. Run: pip install azure-monitor-opentelemetry opentelemetry-instrumentation-flask opentelemetry-instrumentation-openai-v2")

app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# =============================================================================
# Configuration - Microsoft Foundry
# =============================================================================

# Microsoft Foundry Project Configuration
# Use the project endpoint from Foundry portal: Overview > Endpoints and keys
FOUNDRY_PROJECT_ENDPOINT = os.environ.get(
    "FOUNDRY_PROJECT_ENDPOINT", 
    "https://foundry-llmops-canadaeast.services.ai.azure.com/api/projects/proj-llmops-demo"
)
AI_FOUNDRY_RESOURCE = "foundry-llmops-canadaeast"
AI_FOUNDRY_PROJECT = os.environ.get("FOUNDRY_PROJECT_NAME", "proj-llmops-demo")
RESOURCE_GROUP = os.environ.get("AZURE_RESOURCE_GROUP", "rg-llmops-demo")
SUBSCRIPTION_ID = os.environ.get("AZURE_SUBSCRIPTION_ID", "1d53bfb3-a84c-4eb4-8c79-f29dc8424b6a")

# Azure AI Search endpoint (connected via Foundry Hub)
AZURE_SEARCH_ENDPOINT = os.environ.get(
    "AZURE_SEARCH_ENDPOINT",
    "https://search-llmops-canadaeast.search.windows.net"
)

# Model configurations (deployed via Foundry Model Catalog)
CHAT_MODEL_DEPLOYMENT = os.environ.get("CHAT_MODEL", "gpt-4o")
EMBEDDING_MODEL_DEPLOYMENT = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-large")
SEARCH_INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", "walle-products")

# System prompt for the chatbot
SYSTEM_PROMPT = """You are Wall-E, a friendly AI assistant for Wall-E Electronics, a company that sells consumer electronics products including laptops, headphones, smartwatches, and accessories.

Your role:
- Answer customer questions about products, policies, and support
- Be concise, friendly, and helpful like Wall-E the robot
- If you don't know something, say so honestly
- Keep responses under 200 words unless more detail is needed
- When you have context from retrieved documents, base your answers on that information

Key Information:
- Return Policy: 30 days for unopened items, 14 days for opened (15% restocking fee for headphones)
- Laptop Warranty: 2 years
- Smartwatch/Headphones Warranty: 1 year
- Support: 1-800-WALL-E or support@wall-e.com"""


# =============================================================================
# Azure Authentication (RBAC - No API Keys)
# =============================================================================

def get_credential():
    """Get Azure credential - works locally (Azure CLI) and in Azure (Managed Identity)."""
    try:
        # Try Managed Identity first (works when deployed to Azure)
        cred = ManagedIdentityCredential()
        cred.get_token("https://cognitiveservices.azure.com/.default")
        return cred
    except Exception:
        # Fall back to DefaultAzureCredential (works with Azure CLI locally)
        return DefaultAzureCredential()

credential = get_credential()


# =============================================================================
# Microsoft Foundry Project Client
# =============================================================================

def get_project_client():
    """
    Get Microsoft Foundry Project Client.
    Uses the project endpoint directly - no separate Azure OpenAI resource needed.
    """
    return AIProjectClient(
        endpoint=FOUNDRY_PROJECT_ENDPOINT,
        credential=credential
    )

# Initialize project client and OpenAI client via Foundry connection
project_client = get_project_client()

# =============================================================================
# Tracing Configuration - Sends telemetry to Foundry Portal
# =============================================================================

def setup_tracing():
    """
    Configure Azure Monitor tracing for Foundry portal visibility.
    Traces will appear in Foundry Portal > Tracing tab.
    """
    if not TRACING_AVAILABLE:
        print("  ⚠ Tracing not available - install azure-monitor-opentelemetry")
        return False
    
    try:
        # Get Application Insights connection string from Foundry project
        app_insights_conn_str = project_client.telemetry.get_application_insights_connection_string()
        
        if app_insights_conn_str:
            # Configure Azure Monitor with the connection string
            configure_azure_monitor(
                connection_string=app_insights_conn_str,
                enable_live_metrics=True,
            )
            
            # Instrument Flask app for automatic request tracing
            FlaskInstrumentor().instrument_app(app)
            
            # Instrument OpenAI for LLM call tracing 
            # capture_content=True shows actual prompts and responses in traces
            OpenAIInstrumentor().instrument(capture_content=True)
            
            print(f"  ✓ Tracing enabled - View in Foundry Portal > Tracing")
            return True
        else:
            print("  ⚠ No Application Insights connection found in Foundry project")
            return False
    except Exception as e:
        print(f"  ⚠ Tracing setup failed: {e}")
        return False

# Setup tracing (optional - continues without if unavailable)
tracing_enabled = setup_tracing()

# Get Azure OpenAI endpoint - try connection first, fallback to AI Services endpoint
try:
    aoai_connection = project_client.connections.get('aoai-connection')
    aoai_endpoint = aoai_connection.target
except Exception:
    # No separate AOAI connection - use AI Services endpoint directly
    aoai_endpoint = FOUNDRY_PROJECT_ENDPOINT.split('/api/projects/')[0].replace('.services.ai.azure.com', '.cognitiveservices.azure.com') + '/'

openai_client = AzureOpenAI(
    azure_endpoint=aoai_endpoint,
    azure_ad_token_provider=lambda: credential.get_token('https://cognitiveservices.azure.com/.default').token,
    api_version='2024-02-01'
)


# =============================================================================
# RAG Pipeline using Microsoft Foundry Services
# =============================================================================

def search_documents(query: str) -> str:
    """
    Search for relevant documents using Azure AI Search.
    Uses Foundry-connected AI Search with RBAC authentication.
    """
    try:
        from azure.search.documents import SearchClient
        from azure.search.documents.models import VectorizedQuery
        
        # Connect to AI Search
        search_client = SearchClient(
            endpoint=AZURE_SEARCH_ENDPOINT,
            index_name=SEARCH_INDEX_NAME,
            credential=credential
        )
        
        # Get embedding using Microsoft Foundry via OpenAI client
        embedding_response = openai_client.embeddings.create(
            input=query,
            model=EMBEDDING_MODEL_DEPLOYMENT
        )
        query_embedding = embedding_response.data[0].embedding
        
        # Vector search
        vector_query = VectorizedQuery(
            vector=query_embedding,
            k_nearest_neighbors=3,
            fields="content_vector"
        )
        
        results = search_client.search(
            search_text=query,
            vector_queries=[vector_query],
            top=3,
            select=["title", "content"]
        )
        
        # Format results as context
        context_parts = []
        for result in results:
            context_parts.append(f"**{result['title']}**\n{result['content']}")
        
        if context_parts:
            return "\n\n---\n\n".join(context_parts)
        return ""
        
    except Exception as e:
        print(f"Search error: {e}")
        return ""


def generate_response(message: str, history: list, context: str = "") -> dict:
    """
    Generate response using Microsoft Foundry via OpenAI client.
    No separate Azure OpenAI resource needed.
    """
    try:
        # Build system prompt with context
        system_content = SYSTEM_PROMPT
        if context:
            system_content += f"\n\n# Retrieved Information:\n{context}"
        
        # Build messages for chat completion
        messages = [{"role": "system", "content": system_content}]
        
        # Add history (last 10 messages)
        for msg in history[-10:]:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # Add current message
        messages.append({"role": "user", "content": message})
        
        # Call Microsoft Foundry via OpenAI client
        response = openai_client.chat.completions.create(
            model=CHAT_MODEL_DEPLOYMENT,
            messages=messages,
            max_tokens=500,
            temperature=0.3
        )
        
        return {
            'response': response.choices[0].message.content,
            'context_used': bool(context),
            'source': 'Microsoft Foundry',
            'resource': AI_FOUNDRY_RESOURCE,
            'project': AI_FOUNDRY_PROJECT,
            'project_endpoint': FOUNDRY_PROJECT_ENDPOINT,
            'model': CHAT_MODEL_DEPLOYMENT,
            'usage': {
                'prompt_tokens': response.usage.prompt_tokens,
                'completion_tokens': response.usage.completion_tokens,
                'total_tokens': response.usage.total_tokens
            } if hasattr(response, 'usage') and response.usage else None
        }
        
    except Exception as e:
        raise Exception(f"Generation error: {e}")


# =============================================================================
# Flask Routes
# =============================================================================

@app.route('/')
def index():
    """Serve the frontend."""
    return send_from_directory('.', 'index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    """
    Handle chat requests using Azure AI Foundry services.
    Uses Hub connections for Azure OpenAI and AI Search.
    """
    try:
        data = request.json
        message = data.get('message', '')
        history = data.get('history', [])
        use_rag = data.get('use_rag', True)
        
        if not message:
            return jsonify({'error': 'Message is required'}), 400
        
        # Get relevant context using Azure AI Search
        context = ""
        if use_rag:
            context = search_documents(message)
        
        # Generate response using Microsoft Foundry
        result = generate_response(message, history, context)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Health check - shows Microsoft Foundry connectivity."""
    return jsonify({
        'status': 'healthy',
        'auth': 'RBAC (Managed Identity / Azure CLI)',
        'mode': 'Microsoft Foundry',
        'foundry': {
            'resource': AI_FOUNDRY_RESOURCE,
            'project': AI_FOUNDRY_PROJECT,
            'resource_group': RESOURCE_GROUP,
            'project_endpoint': FOUNDRY_PROJECT_ENDPOINT
        },
        'inference': {
            'type': 'Microsoft Foundry Inference API',
            'chat_model': CHAT_MODEL_DEPLOYMENT,
            'embedding_model': EMBEDDING_MODEL_DEPLOYMENT
        },
        'search': {
            'type': 'Azure AI Search',
            'endpoint': AZURE_SEARCH_ENDPOINT,
            'index': SEARCH_INDEX_NAME
        }
    })


@app.route('/api/config', methods=['GET'])
def get_config():
    """Return configuration for frontend display."""
    return jsonify({
        'mode': 'Microsoft Foundry',
        'resource': AI_FOUNDRY_RESOURCE,
        'project': AI_FOUNDRY_PROJECT,
        'foundry_project_endpoint': FOUNDRY_PROJECT_ENDPOINT,
        'search_endpoint': AZURE_SEARCH_ENDPOINT,
        'chat_model': CHAT_MODEL_DEPLOYMENT,
        'embedding_model': EMBEDDING_MODEL_DEPLOYMENT,
        'search_index': SEARCH_INDEX_NAME
    })


if __name__ == '__main__':
    print("=" * 60)
    print("  Wall-E Electronics - RAG Chatbot")
    print("  Powered by Microsoft Foundry")
    print("=" * 60)
    
    print("\n  Authentication: RBAC (Managed Identity / Azure CLI)")
    
    print(f"\n  Microsoft Foundry:")
    print(f"    - Resource: {AI_FOUNDRY_RESOURCE}")
    print(f"    - Project: {AI_FOUNDRY_PROJECT}")
    print(f"    - Project Endpoint: {FOUNDRY_PROJECT_ENDPOINT}")
    
    print(f"\n  Inference (via Foundry - no separate Azure OpenAI):")
    print(f"    - Chat Model: {CHAT_MODEL_DEPLOYMENT}")
    print(f"    - Embedding Model: {EMBEDDING_MODEL_DEPLOYMENT}")
    
    print(f"\n  Azure AI Search:")
    print(f"    - Endpoint: {AZURE_SEARCH_ENDPOINT}")
    print(f"    - Index: {SEARCH_INDEX_NAME}")
    
    print("\n  Starting server at http://localhost:5000")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=5000, debug=True)
