# Enterprise Knowledge AI

Enterprise Knowledge AI is a retrieval-augmented generation (RAG) prototype for searching PDF documents. Upload a PDF, ask a question in French, and open the cited page to verify the answer. Each citation includes the passage used to answer the question. When the indexed documents provide too little evidence, the application can abstain.

## Quick start

**Requirements** — Docker with Compose v2 and an OpenAI API key with access to `text-embedding-3-small` and `gpt-5-mini`. OpenAI bills embedding and generation requests to your account.

From the repository root, create the environment file:

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env` and start the services:

```bash
docker compose up --build -d
docker compose ps
```

Open [localhost:3000](http://localhost:3000). The web interface listens on the local loopback address. PostgreSQL, RustFS, and FastAPI run on the internal Docker network. FastAPI reads the API key, and Git ignores `.env`.

```bash
docker compose logs -f api   # Follow API logs for upload or generation errors
docker compose down          # Stop the services and keep their data
```

The `postgres` and `objects` volumes store the search index and the original PDFs, respectively. Running `docker compose down -v` deletes both volumes and all imported documents.

## Demo

1. Upload the [sample refund policy PDF](demo/politique-remboursement.pdf). Page 1 covers France, and page 2 covers Switzerland.
2. Click **Utiliser une question d’exemple** (Use an example question), then **Poser la question** (Ask). The expected answer says Swiss customers have **30 days from delivery** to submit a request through the support portal. They need to include their invoice and order number.
3. Open **politique-remboursement.pdf · page 2** to verify the answer against the source. The link passes the `#page=2` fragment to the browser’s PDF viewer.
4. Ask “Quel délai de remboursement s’applique aux clients canadiens ?” (“What is the refund deadline for Canadian customers?”). The sample PDF does not cover Canada. The expected result is an abstention without citations.

## Architecture

```mermaid
flowchart LR
    Browser["Browser"] --> Next["Next.js"]
    Next --> API["FastAPI"]
    API --> Split["pypdf + LlamaIndex"]
    API --> DB["PostgreSQL + pgvector"]
    API --> Storage["Private S3-compatible storage via RustFS"]
    API --> OpenAI["OpenAI embeddings and Responses API"]
```

| Stage | Implementation |
| --- | --- |
| Upload | FastAPI validates the file type and size. pypdf extracts text page by page. LlamaIndex splits it into 360-token chunks with a 45-token overlap. Each chunk retains its physical page number, starting at 1. |
| Indexing | OpenAI generates embeddings in batches. PostgreSQL stores the chunks, their vectors, and the full-text search terms. RustFS stores the original PDF through its S3-compatible API. The document appears in the library after the object upload and the PostgreSQL transaction succeed. |
| Retrieval | pgvector ranks chunks by cosine distance. PostgreSQL full-text search ranks chunks that share terms with the question, using French text normalization. Reciprocal Rank Fusion combines up to 20 candidates from each search. The top five chunks go to the generation model. |
| Generation | GPT-5 mini receives the question and the retrieved chunks. Its structured output contains the answer and chunk IDs. FastAPI checks that every ID belongs to the supplied context and builds the citations from database records. Check the quoted passage or PDF page to verify that it supports the answer. |

### HTTP API

Next.js exposes these routes on port 3000.

| Method | Route | Behavior |
| --- | --- | --- |
| `POST` | `/api/documents` | Accepts a multipart upload in the `file` field and returns the document metadata after indexing. |
| `GET` | `/api/documents` | Lists indexed documents. |
| `GET` | `/api/documents/{id}/pdf` | Reads the original from S3 and serves it inline as a PDF. |
| `POST` | `/api/ask` | Accepts `{"question": "..."}` and returns the answer, citations, and API-side latency in milliseconds. |

```bash
curl --fail-with-body -F 'file=@demo/politique-remboursement.pdf'   http://localhost:3000/api/documents
curl --fail-with-body -H 'Content-Type: application/json'   -d '{"question":"Quelle est la procédure de remboursement en Suisse ?"}'   http://localhost:3000/api/ask
```

## Verification

GitHub Actions starts the Docker Compose stack, checks the home page, and runs the FastAPI integration test against PostgreSQL 17 with pgvector. The test mocks OpenAI responses at the HTTP layer and uses Moto for S3. It checks invalid file rejection, sample PDF ingestion, retrieval of the Swiss policy, the page 2 citation, the integrity of the served PDF, abstention, and rejection of a fabricated citation ID. The checks run without an OpenAI key or API charges.

To run the integration test locally, use a PostgreSQL test database with pgvector and a database user that can create the extension and a schema.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -r api/requirements-test.txt
TEST_DATABASE_URL='postgresql://user:password@localhost:5432/knowledge'   python -m unittest discover -s api -v
```

To build the web interface locally with Node.js 22:

```bash
cd web
npm ci
npm run build
```

## Prototype scope

- **Single local workspace.** Use synthetic documents for the demo. Shared use requires authentication and access controls for search, citations, and original PDFs.
- **Text-based PDFs.** Upload one file at a time, up to 8 MiB, 100 pages, and 500 chunks. Scanned PDFs without a text layer require OCR. Indexing runs during the upload request.
- **Data sent to OpenAI.** The embeddings API receives document chunks and questions. The generation API receives the question and up to five retrieved chunks. The application sets `store: false` for generation. OpenAI’s retention policies still apply. [OpenAI data controls](https://developers.openai.com/api/docs/guides/your-data)
- **Hybrid search with exact vector ranking.** The interface shows the current request latency. Cross-encoder reranking, document permissions, conversation history, versioning, and evaluation of Recall@5, citation precision, grounded answer rate, p95 latency, and cost per question are future work.
