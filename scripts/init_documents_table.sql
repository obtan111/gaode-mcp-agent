CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    vector vector(1024) NOT NULL,
    filename VARCHAR(255),
    page_number INTEGER,
    category VARCHAR(100),
    metadata JSONB,
    source_text TEXT,
    kb_name VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_documents_vector ON documents USING ivfflat (vector vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_documents_category ON documents (category);
CREATE INDEX IF NOT EXISTS idx_documents_kb_name ON documents (kb_name);
CREATE INDEX IF NOT EXISTS idx_documents_filename ON documents (filename);