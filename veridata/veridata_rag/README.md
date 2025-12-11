# VeriRag Core

VeriRag Core is a lightweight, containerized RAG (Retrieval-Augmented Generation) engine designed for internal use. It allows you to ingest documents and query them using Google Gemini.

## Features

- **Pure Gemini Stack**: Uses Google Gemini for both specific Embeddings (768-dim) and LLM Answer Generation.
- **RAG Engine**: Vector similarity search using PostgreSQL + pgvector.
- **Web Dashboard**: Simple UI for managing tenants and uploading files.
- **JSON API**: Programmatic access for external system integration.

## Setup

1.  **Environment Variables**:
    Copy `.env.example` to `.env` and set your keys:
    ```bash
    cp .env.example .env
    ```
    Required variables:
    - `GOOGLE_API_KEY`: A valid API key from Google AI Studio.
    - `GEMINI_MODEL`: e.g., `gemini-1.5-flash` or `gemini-2.0-flash`.

2.  **Run with Docker**:
    ```bash
    docker compose up -d --build
    ```

## Usage

### Web Dashboard
Open [http://localhost:8000](http://localhost:8000).
- **Default User**: `admin`
- **Default Password**: `admin`

### API Integration (External Callers)

To call the RAG engine from another system, use the `/api/query` endpoint.

**Endpoint:** `POST /api/query`
**Authentication:** Basic Auth (`admin`/`admin` by default).

**Request (JSON):**
```json
{
  "tenant_id": "YOUR_TENANT_UUID",
  "query": "Your question here"
}
```

**Response (JSON):**
```json
{
  "answer": "The generated answer based on your documents."
}
```

**Example (cURL):**
```bash
curl -X POST http://localhost:8000/api/query \
  -u admin:admin \
  -H "Content-Type: application/json" \
  -d '{"tenant_id": "your-uuid", "query": "Hello world"}'
```
