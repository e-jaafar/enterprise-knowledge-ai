import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

import boto3
import psycopg
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import Response
from openai import APIError, OpenAI
from psycopg.rows import dict_row
from pydantic import BaseModel, Field, field_validator

from rag import HYBRID_SEARCH, InvalidPDF, embeddings, extract_passages, generate

MAX_BYTES = 8 * 1024 * 1024
logger = logging.getLogger(__name__)


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=1000)

    @field_validator("question", mode="before")
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


def connect():
    return psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row, connect_timeout=5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ai = OpenAI(timeout=35, max_retries=1)
    app.state.bucket = os.environ["S3_BUCKET"]
    endpoint = os.getenv("S3_ENDPOINT")
    app.state.storage = boto3.client(
        "s3",
        endpoint_url=endpoint,
        config=Config(connect_timeout=5, read_timeout=15, s3={"addressing_style": "path"}),
    )
    if endpoint:
        try:
            app.state.storage.head_bucket(Bucket=app.state.bucket)
        except ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] != 404:
                raise
            app.state.storage.create_bucket(Bucket=app.state.bucket)
    with connect() as db:
        db.execute(Path(__file__).with_name("schema.sql").read_text())
    try:
        yield
    finally:
        app.state.ai.close()
        app.state.storage.close()


app = FastAPI(title="Enterprise Knowledge AI", lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ready"}


@app.get("/api/documents")
def list_documents():
    with connect() as db:
        return db.execute(
            "SELECT id, filename, pages, created_at FROM documents ORDER BY created_at DESC, id"
        ).fetchall()


@app.post("/api/documents", status_code=201)
def import_document(file: UploadFile):
    raw = file.file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(413, "La taille maximale est de 8 Mio par fichier.")
    filename = Path((file.filename or "").replace("\\", "/")).name.strip()
    if not filename.lower().endswith(".pdf") or len(filename) > 200 or chr(0) in filename:
        raise HTTPException(422, "Le fichier doit avoir un nom PDF de 200 caractères maximum.")
    try:
        pages, passages = extract_passages(raw)
        vectors = embeddings(app.state.ai, [content for _, content in passages])
    except InvalidPDF as exc:
        raise HTTPException(422, str(exc)) from exc
    except APIError as exc:
        raise HTTPException(502, "Le service d’indexation OpenAI est indisponible.") from exc

    document_id = uuid4()
    key = f"{document_id}.pdf"
    stored = False
    try:
        with connect() as db:
            document = db.execute(
                "INSERT INTO documents (id, filename, pages) VALUES (%s, %s, %s) RETURNING *",
                (document_id, filename, pages),
            ).fetchone()
            db.cursor().executemany(
                "INSERT INTO passages (document_id, page, content, embedding) VALUES (%s, %s, %s, %s::vector)",
                [(document_id, page, content, vector) for (page, content), vector in zip(passages, vectors, strict=True)],
            )
            app.state.storage.put_object(
                Bucket=app.state.bucket, Key=key, Body=raw, ContentType="application/pdf"
            )
            stored = True
    except (psycopg.Error, BotoCoreError, ClientError) as exc:
        if stored:
            logger.warning("Vérifier l’objet S3 %s après échec de transaction.", key)
        raise HTTPException(503, "Le document n’a pas pu être enregistré.") from exc
    return document


@app.get("/api/documents/{document_id}/pdf")
def open_pdf(document_id: UUID):
    with connect() as db:
        if db.execute("SELECT 1 FROM documents WHERE id = %s", (document_id,)).fetchone() is None:
            raise HTTPException(404, "Document introuvable.")
    try:
        obj = app.state.storage.get_object(Bucket=app.state.bucket, Key=f"{document_id}.pdf")
        with obj["Body"] as body:
            data = body.read()
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(503, "Le PDF est temporairement inaccessible.") from exc
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "inline", "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


@app.post("/api/ask")
def ask(body: Question):
    started = perf_counter()
    try:
        with connect() as db:
            has_passages = db.execute("SELECT 1 FROM passages LIMIT 1").fetchone()
        candidates = []
        if has_passages:
            (vector,) = embeddings(app.state.ai, [body.question])
            with connect() as db:
                candidates = db.execute(
                    HYBRID_SEARCH, {"vector": vector, "question": body.question}
                ).fetchall()
        answer = generate(app.state.ai, body.question, candidates)
    except APIError as exc:
        raise HTTPException(502, "Le service de réponse OpenAI est indisponible.") from exc
    return {**answer, "latency_ms": round((perf_counter() - started) * 1000)}
