"""
LLMOps Workshop - Create Azure AI Search Index from Document Files
===================================================================
This script reads documents from the data/ folder (txt, md, pdf) and creates
a vector search index in Azure AI Search for the Wall-E Electronics chatbot.

Supported file types:
- .txt files (plain text)
- .md files (markdown)
- .pdf files (PDF documents)

Authentication: Uses Azure Identity (DefaultAzureCredential) - no API keys required
"""

import os
import re
from pathlib import Path
from datetime import datetime
from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
)
from openai import AzureOpenAI

# Try to import PyPDF2 for PDF support
try:
    from PyPDF2 import PdfReader
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False
    print("Warning: PyPDF2 not installed. PDF files will be skipped.")
    print("Install with: pip install PyPDF2")

# Configuration from environment variables
AZURE_SEARCH_ENDPOINT = os.environ.get("AZURE_SEARCH_ENDPOINT", "https://search-llmops-dev-naxfrjtmsmlvo.search.windows.net")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://aoai-llmops-eastus.openai.azure.com/")
EMBEDDING_MODEL = os.environ.get("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
INDEX_NAME = os.environ.get("AZURE_SEARCH_INDEX_NAME", "contoso-products")

# Path to data folder (relative to script location)
SCRIPT_DIR = Path(__file__).parent.parent
DATA_FOLDER = SCRIPT_DIR / "data"


def read_text_file(file_path: Path) -> str:
    """Read content from a text or markdown file."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def read_pdf_file(file_path: Path) -> str:
    """Read content from a PDF file using PyPDF2."""
    if not PDF_SUPPORT:
        return ""
    
    reader = PdfReader(file_path)
    text_parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return "\n".join(text_parts)


def extract_category(content: str) -> str:
    """Extract category from document content if present."""
    # Look for "Category: X" pattern at the end of the document
    match = re.search(r"Category:\s*(\w+)", content, re.IGNORECASE)
    if match:
        return match.group(1).capitalize()
    return "General"


def generate_document_id(file_name: str) -> str:
    """Generate a document ID from the filename."""
    # Remove extension and replace spaces/special chars with hyphens
    name_without_ext = file_name.rsplit(".", 1)[0]
    doc_id = re.sub(r"[^a-zA-Z0-9]+", "-", name_without_ext).lower().strip("-")
    return doc_id


def load_documents_from_folder(folder_path: Path) -> list:
    """Load all documents from the data folder."""
    documents = []
    
    if not folder_path.exists():
        print(f"Warning: Data folder not found at {folder_path}")
        return documents
    
    supported_extensions = {".txt", ".md", ".pdf"}
    
    for file_path in folder_path.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
            print(f"  Reading: {file_path.name}")
            
            # Read content based on file type
            if file_path.suffix.lower() == ".pdf":
                content = read_pdf_file(file_path)
            else:
                content = read_text_file(file_path)
            
            if not content.strip():
                print(f"    Skipping empty file: {file_path.name}")
                continue
            
            # Extract title from first line or filename
            lines = content.strip().split("\n")
            title = lines[0].strip().lstrip("#").strip() if lines else file_path.stem
            
            # Create document
            doc = {
                "id": generate_document_id(file_path.name),
                "title": title[:200],  # Limit title length
                "category": extract_category(content),
                "content": content,
                "source_file": file_path.name,
                "last_updated": datetime.now().strftime("%Y-%m-%d")
            }
            documents.append(doc)
            print(f"    Loaded: {doc['title'][:50]}...")
    
    return documents


def create_search_index(index_client: SearchIndexClient) -> None:
    """Create the search index with vector search configuration."""
    
    # Define the index schema
    fields = [
        SearchField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
        SearchField(name="title", type=SearchFieldDataType.String, searchable=True, filterable=True),
        SearchField(name="category", type=SearchFieldDataType.String, searchable=True, filterable=True, facetable=True),
        SearchField(name="content", type=SearchFieldDataType.String, searchable=True),
        SearchField(name="source_file", type=SearchFieldDataType.String, filterable=True),
        SearchField(name="last_updated", type=SearchFieldDataType.String, filterable=True, sortable=True),
        SearchField(
            name="content_vector",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=3072,  # text-embedding-3-large dimension
            vector_search_profile_name="myHnswProfile"
        ),
    ]
    
    # Configure vector search
    vector_search = VectorSearch(
        algorithms=[
            HnswAlgorithmConfiguration(name="myHnsw"),
        ],
        profiles=[
            VectorSearchProfile(
                name="myHnswProfile",
                algorithm_configuration_name="myHnsw",
            ),
        ],
    )
    
    # Configure semantic search
    semantic_config = SemanticConfiguration(
        name="my-semantic-config",
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="title"),
            content_fields=[SemanticField(field_name="content")],
            keywords_fields=[SemanticField(field_name="category")]
        ),
    )
    
    semantic_search = SemanticSearch(configurations=[semantic_config])
    
    # Create the index
    index = SearchIndex(
        name=INDEX_NAME,
        fields=fields,
        vector_search=vector_search,
        semantic_search=semantic_search
    )
    
    # Delete existing index if it exists
    try:
        index_client.delete_index(INDEX_NAME)
        print(f"  Deleted existing index: {INDEX_NAME}")
    except Exception:
        pass  # Index doesn't exist
    
    # Create new index
    index_client.create_index(index)
    print(f"  Created index: {INDEX_NAME}")


def generate_embeddings(openai_client: AzureOpenAI, text: str) -> list:
    """Generate embeddings for a text using Azure OpenAI."""
    # Truncate text if too long (max ~8000 tokens for text-embedding-3-large)
    max_chars = 30000
    if len(text) > max_chars:
        text = text[:max_chars]
    
    response = openai_client.embeddings.create(
        input=text,
        model=EMBEDDING_MODEL
    )
    return response.data[0].embedding


def index_documents(search_client: SearchClient, openai_client: AzureOpenAI, documents: list) -> None:
    """Generate embeddings and index documents."""
    
    indexed_docs = []
    
    for doc in documents:
        print(f"  Processing: {doc['title'][:50]}...")
        
        # Generate embedding for content
        embedding = generate_embeddings(openai_client, doc["content"])
        
        # Prepare document for indexing
        indexed_doc = {
            "id": doc["id"],
            "title": doc["title"],
            "category": doc["category"],
            "content": doc["content"],
            "source_file": doc["source_file"],
            "last_updated": doc["last_updated"],
            "content_vector": embedding
        }
        indexed_docs.append(indexed_doc)
    
    # Upload documents
    result = search_client.upload_documents(documents=indexed_docs)
    
    succeeded = sum(1 for r in result if r.succeeded)
    print(f"  Indexed {succeeded}/{len(indexed_docs)} documents successfully")


def main():
    """Main function to create index and load documents."""
    
    print("=" * 60)
    print("  Wall-E Electronics - Document Indexer")
    print("  LLMOps Workshop Demo")
    print("=" * 60)
    
    # Initialize Azure credential
    print("\n[1/5] Authenticating with Azure...")
    credential = DefaultAzureCredential()
    print("  Using DefaultAzureCredential (RBAC)")
    
    # Initialize clients
    print("\n[2/5] Initializing clients...")
    
    index_client = SearchIndexClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        credential=credential
    )
    print(f"  Search endpoint: {AZURE_SEARCH_ENDPOINT}")
    
    search_client = SearchClient(
        endpoint=AZURE_SEARCH_ENDPOINT,
        index_name=INDEX_NAME,
        credential=credential
    )
    
    openai_client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        azure_ad_token_provider=lambda: credential.get_token("https://cognitiveservices.azure.com/.default").token,
        api_version="2024-02-01"
    )
    print(f"  OpenAI endpoint: {AZURE_OPENAI_ENDPOINT}")
    print(f"  Embedding model: {EMBEDDING_MODEL}")
    
    # Load documents from data folder
    print(f"\n[3/5] Loading documents from {DATA_FOLDER}...")
    documents = load_documents_from_folder(DATA_FOLDER)
    
    if not documents:
        print("  No documents found! Make sure the data/ folder contains .txt, .md, or .pdf files.")
        return
    
    print(f"  Loaded {len(documents)} documents")
    
    # Create search index
    print(f"\n[4/5] Creating search index '{INDEX_NAME}'...")
    create_search_index(index_client)
    
    # Index documents
    print("\n[5/5] Generating embeddings and indexing documents...")
    index_documents(search_client, openai_client, documents)
    
    print("\n" + "=" * 60)
    print("  Indexing Complete!")
    print("=" * 60)
    print(f"\n  Index: {INDEX_NAME}")
    print(f"  Documents: {len(documents)}")
    print(f"  Endpoint: {AZURE_SEARCH_ENDPOINT}")
    print("\n  Document files processed:")
    for doc in documents:
        print(f"    - {doc['source_file']} ({doc['category']})")
    
    print("\n  Next step: Run the chatbot with 'python 04-frontend/app.py'")


if __name__ == "__main__":
    main()


