CREATE_EXTENSIONS_SQL = """
CREATE EXTENSION IF NOT EXISTS pgvector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
"""


CREATE_DOCUMENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    content TEXT NOT NULL,
    content_hash VARCHAR(32),
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
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents (content_hash);
"""

ALTER_DOCUMENTS_TABLE_ADD_HASH_SQL = """
ALTER TABLE IF EXISTS documents ADD COLUMN IF NOT EXISTS content_hash VARCHAR(32);
CREATE INDEX IF NOT EXISTS idx_documents_content_hash ON documents (content_hash);
"""


CREATE_CHAT_SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS chat_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    summary TEXT,
    messages JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_session_created_at ON chat_session (created_at DESC);
"""


CREATE_MCP_CALL_LOG_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS mcp_call_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tool_name VARCHAR(255) NOT NULL,
    parameters JSONB,
    result JSONB,
    call_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    token_usage INTEGER,
    session_id UUID
);

CREATE INDEX IF NOT EXISTS idx_mcp_call_log_tool_name ON mcp_call_log (tool_name);
CREATE INDEX IF NOT EXISTS idx_mcp_call_log_call_time ON mcp_call_log (call_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_call_log_session_id ON mcp_call_log (session_id);
"""


CREATE_TRAVEL_PLAN_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS travel_plan (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    destination VARCHAR(255) NOT NULL,
    days INTEGER NOT NULL,
    budget NUMERIC(12, 2),
    plan_data JSONB NOT NULL,
    weather_info JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_travel_plan_destination ON travel_plan (destination);
CREATE INDEX IF NOT EXISTS idx_travel_plan_created_at ON travel_plan (created_at DESC);
"""


ALL_SCHEMAS_SQL = "\n".join([
    CREATE_EXTENSIONS_SQL,
    CREATE_DOCUMENTS_TABLE_SQL,
    CREATE_CHAT_SESSION_TABLE_SQL,
    CREATE_MCP_CALL_LOG_TABLE_SQL,
    CREATE_TRAVEL_PLAN_TABLE_SQL,
])


def get_create_extensions_sql() -> str:
    return CREATE_EXTENSIONS_SQL


def get_create_documents_table_sql() -> str:
    return CREATE_DOCUMENTS_TABLE_SQL


def get_create_chat_session_table_sql() -> str:
    return CREATE_CHAT_SESSION_TABLE_SQL


def get_create_mcp_call_log_table_sql() -> str:
    return CREATE_MCP_CALL_LOG_TABLE_SQL


def get_create_travel_plan_table_sql() -> str:
    return CREATE_TRAVEL_PLAN_TABLE_SQL


def get_all_schemas_sql() -> str:
    return ALL_SCHEMAS_SQL


def get_alter_documents_table_add_hash_sql() -> str:
    return ALTER_DOCUMENTS_TABLE_ADD_HASH_SQL