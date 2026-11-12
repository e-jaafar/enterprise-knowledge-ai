CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id uuid PRIMARY KEY,
    filename text NOT NULL,
    pages integer NOT NULL CHECK (pages > 0),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS passages (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page integer NOT NULL CHECK (page > 0),
    content text NOT NULL,
    embedding vector(1536) NOT NULL,
    terms tsvector GENERATED ALWAYS AS (to_tsvector('french', content)) STORED
);

CREATE INDEX IF NOT EXISTS passages_terms_idx ON passages USING gin (terms);
