CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS chat_session (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    summary TEXT,
    messages JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_chat_session_created_at ON chat_session (created_at DESC);

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