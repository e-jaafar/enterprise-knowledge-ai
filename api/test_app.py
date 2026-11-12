import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import httpx
import psycopg
from fastapi.testclient import TestClient
from moto import mock_aws
from openai import OpenAI
from psycopg import sql

from app import app
from rag import ABSTENTION

PDF = Path(__file__).resolve().parents[1] / "demo" / "politique-remboursement.pdf"


def model_response(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    if request.url.path == "/v1/embeddings":
        data = []
        for index, text in enumerate(payload["input"]):
            vector = [0.0] * 1536
            vector[int("suisse" in text.lower())] = 1.0
            data.append({"index": index, "object": "embedding", "embedding": vector})
        return httpx.Response(200, json={"object": "list", "model": payload["model"], "data": data})

    assert request.url.path == "/v1/responses"
    assert payload["store"] is False
    question = json.loads(payload["input"])
    swiss = question["passages"][0]
    if "Canada" in question["question"]:
        result = {"answer": "", "citation_ids": []}
    elif "inventée" in question["question"]:
        result = {"answer": "Citation invalide.", "citation_ids": [999999]}
    else:
        assert swiss["page"] == 2, swiss
        result = {"answer": "Les clients suisses ont 30 jours.", "citation_ids": [swiss["id"]]}
    return httpx.Response(200, json={
        "id": "resp_fixture",
        "object": "response",
        "status": "completed",
        "output": [{
            "id": "msg_fixture",
            "type": "message",
            "role": "assistant",
            "status": "completed",
            "content": [{"type": "output_text", "text": json.dumps(result), "annotations": []}],
        }],
    })


class RAGIntegrationTest(unittest.TestCase):
    def test_import_query_citation_and_abstention(self):
        db_url = os.environ["TEST_DATABASE_URL"]
        schema = "test_" + uuid4().hex
        with psycopg.connect(db_url, autocommit=True) as db:
            db.execute("CREATE EXTENSION IF NOT EXISTS vector")
            db.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            self.addCleanup(lambda: drop_schema(db_url, schema))

        test_url = psycopg.conninfo.make_conninfo(db_url, options=f"-c search_path={schema},public")
        env = {"DATABASE_URL": test_url, "S3_BUCKET": "test-documents", "AWS_DEFAULT_REGION": "us-east-1"}
        ai = OpenAI(api_key="test-only", http_client=httpx.Client(transport=httpx.MockTransport(model_response)))
        with mock_aws(), patch.dict(os.environ, env), patch("app.OpenAI", return_value=ai):
            import boto3

            boto3.client("s3").create_bucket(Bucket=env["S3_BUCKET"])
            with TestClient(app) as client:
                self.assertEqual(client.get("/api/documents").json(), [])
                self.assertEqual(client.post("/api/ask", json={"question": "Suisse ?"}).json()["answer"], ABSTENTION)
                rejected = client.post("/api/documents", files={"file": ("invalid.pdf", b"not a PDF")})
                self.assertEqual(rejected.status_code, 422)
                pdf = PDF.read_bytes()
                imported = client.post("/api/documents", files={"file": (PDF.name, pdf, "application/pdf")})
                self.assertEqual(imported.status_code, 201, imported.text)
                self.assertEqual(imported.json()["pages"], 2)
                self.assertEqual(client.get("/api/documents").json(), [imported.json()])

                asked = client.post("/api/ask", json={"question": "Quel délai de remboursement en Suisse ?"})
                self.assertEqual(asked.status_code, 200, asked.text)
                self.assertIn("30 jours", asked.json()["answer"])
                citation, = asked.json()["citations"]
                self.assertEqual(citation["page"], 2)
                self.assertIn("30 jours", citation["excerpt"])
                self.assertTrue(citation["url"].endswith("#page=2"))
                source = client.get(citation["url"].split("#")[0])
                self.assertEqual(source.headers["content-type"], "application/pdf")
                self.assertEqual(source.content, pdf)

                for question in ("Et au Canada ?", "Citation inventée ?"):
                    answer = client.post("/api/ask", json={"question": question}).json()
                    self.assertEqual(answer["answer"], ABSTENTION)
                    self.assertEqual(answer["citations"], [])


def drop_schema(db_url: str, schema: str):
    with psycopg.connect(db_url, autocommit=True) as db:
        db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
