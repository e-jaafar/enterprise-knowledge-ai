"use client";

import { useEffect, useState } from "react";

const example = "Quelle est notre procédure de remboursement pour les clients suisses ?";

async function request(path, options) {
  const response = await fetch(`/api/${path}`, options);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(typeof error.detail === "string" ? error.detail : "La requête a échoué.");
  }
  return response.json();
}

export default function Home() {
  const [documents, setDocuments] = useState([]);
  const [libraryError, setLibraryError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [importStatus, setImportStatus] = useState("");
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [answerError, setAnswerError] = useState("");
  const [result, setResult] = useState(null);

  useEffect(() => {
    request("documents").then(setDocuments).catch((error) => setLibraryError(error.message));
  }, []);

  async function importFile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    setUploading(true);
    setLibraryError("");
    setImportStatus("");
    try {
      const document = await request("documents", { method: "POST", body: new FormData(form) });
      setDocuments((items) => [document, ...items.filter((item) => item.id !== document.id)]);
      setImportStatus(`${document.filename} est prêt.`);
      form.reset();
    } catch (error) {
      setLibraryError(error.message);
    } finally {
      setUploading(false);
    }
  }

  async function ask(event) {
    event.preventDefault();
    const submitted = question.trim();
    if (!submitted) return;
    setAsking(true);
    setAnswerError("");
    setResult(null);
    try {
      const answer = await request("ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: submitted }),
      });
      setResult({ ...answer, question: submitted });
    } catch (error) {
      setAnswerError(error.message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <>
      <header className="masthead">
        <span className="mark" aria-hidden="true">K</span>
        <span>Enterprise Knowledge AI</span>
      </header>
      <main className="workspace">
        <aside aria-labelledby="library">
          <div className="section-title">
            <h2 id="library">Bibliothèque</h2>
            <span>{documents.length}</span>
          </div>
          <form className="import" onSubmit={importFile}>
            <label htmlFor="file">Ajouter un document PDF</label>
            <input id="file" type="file" name="file" accept=".pdf,application/pdf" required disabled={uploading} />
            <p className="hint">Texte sélectionnable · 8 Mio maximum</p>
            <button type="submit" disabled={uploading}>{uploading ? "Indexation…" : "Importer"}</button>
          </form>
          <p className="status" role="status">{importStatus}</p>
          {libraryError && <p className="error" role="alert">{libraryError}</p>}
          {documents.length > 0 && (
            <ul className="documents">
              {documents.map((document) => (
                <li key={document.id}>
                  <a href={`/api/documents/${document.id}/pdf`} target="_blank" rel="noreferrer">
                    {document.filename}
                  </a>
                  <small>{document.pages} {document.pages === 1 ? "page" : "pages"}</small>
                </li>
              ))}
            </ul>
          )}
        </aside>
        <section className="query" aria-labelledby="query">
          <h1 id="query">Interroger les documents</h1>
          <form onSubmit={ask}>
            <label htmlFor="question">Votre question</label>
            <textarea id="question" value={question} onChange={(event) => setQuestion(event.target.value)}
              rows={3} maxLength={1000} required placeholder="Posez une question sur vos documents…" />
            <div className="query-actions">
              <button className="example" type="button" onClick={() => setQuestion(example)}>Utiliser une question d’exemple</button>
              <button className="primary" type="submit" disabled={asking || !question.trim()}>
                {asking ? "Recherche…" : "Poser la question"}
              </button>
            </div>
          </form>
          <div aria-live="polite" aria-busy={asking}>
            {answerError && <p className="error" role="alert">{answerError}</p>}
            {result && (
              <article className="result">
                <div className="section-title">
                  <h2>Réponse</h2>
                  <small>{result.latency_ms} ms</small>
                </div>
                <p className="hint">{result.question}</p>
                <p className="answer">{result.answer}</p>
                {result.citations.length > 0 && (
                  <>
                    <h3>Sources</h3>
                    <ol className="sources">
                      {result.citations.map((source) => (
                        <li key={source.id}>
                          <a href={source.url} target="_blank" rel="noreferrer">
                            {source.filename} · page {source.page}
                          </a>
                          <blockquote>{source.excerpt}</blockquote>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
              </article>
            )}
          </div>
        </section>
      </main>
    </>
  );
}
