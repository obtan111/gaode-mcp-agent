import sys
import os
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config.settings import Config

def execute_via_supabase_rest(sql):
    try:
        config = Config()
        url = config.SUPABASE_URL
        api_key = config.SUPABASE_KEY
        
        rest_url = f"{url}/rest/v1/rpc/execute_sql"
        
        headers = {
            "apikey": api_key,
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        
        data = {"sql": sql}
        
        response = requests.post(rest_url, headers=headers, json=data, timeout=30)
        
        if response.status_code == 200:
            print(f"  ✅ 成功")
            return True
        else:
            print(f"  ❌ 失败: {response.status_code} - {response.text[:100]}")
            return False
            
    except Exception as e:
        print(f"  ❌ 失败: {str(e)[:100]}")
        return False

def create_rpc_function():
    config = Config()
    url = config.SUPABASE_URL
    api_key = config.SUPABASE_KEY
    
    create_function_sql = """
    CREATE OR REPLACE FUNCTION execute_sql(sql text) RETURNS text AS $$
    BEGIN
        EXECUTE sql;
        RETURN 'success';
    END;
    $$ LANGUAGE plpgsql SECURITY DEFINER;
    
    GRANT EXECUTE ON FUNCTION execute_sql(text) TO anon;
    """
    
    rest_url = f"{url}/rest/v1/"
    headers = {
        "apikey": api_key,
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    
    try:
        response = requests.post(
            f"{url}/rest/v1/rpc",
            headers=headers,
            json={"query": create_function_sql},
            timeout=30
        )
        print(f"创建 RPC 函数: {response.status_code}")
        return True
    except Exception as e:
        print(f"创建 RPC 函数失败: {str(e)}")
        return False

def execute_via_supabase_client(sql):
    try:
        from src.database.supabase_client import get_supabase_client
        
        client = get_supabase_client()
        
        def exec_func(sb_client):
            return sb_client.rpc("execute_sql", {"sql": sql}).execute()
        
        result = client.execute_with_client(exec_func)
        print(f"  ✅ 成功")
        return True
    except Exception as e:
        print(f"  ❌ 失败: {str(e)[:100]}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("迁移向量维度: 1536 -> 1024")
    print("=" * 60)
    
    sql_commands = [
        "DROP INDEX IF EXISTS idx_documents_vector",
        "DROP TABLE IF EXISTS documents",
        """
            CREATE TABLE documents (
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
            )
        """,
        "CREATE INDEX idx_documents_vector ON documents USING ivfflat (vector vector_cosine_ops)",
        "CREATE INDEX idx_documents_category ON documents (category)",
        "CREATE INDEX idx_documents_kb_name ON documents (kb_name)",
        "CREATE INDEX idx_documents_filename ON documents (filename)",
    ]
    
    print("\n=== 方法1: 使用 Supabase RPC ===")
    print("\n1. 尝试创建 execute_sql RPC 函数...")
    create_rpc_function()
    
    print("\n2. 执行迁移命令...")
    for cmd in sql_commands:
        cmd_name = cmd.split()[0]
        print(f"\n{cmd_name}...")
        execute_via_supabase_client(cmd)
    
    print("\n" + "=" * 60)
    print("如果迁移失败，请手动在 Supabase Dashboard 中执行以下 SQL:")
    print("=" * 60)
    print()
    for cmd in sql_commands:
        print(cmd)
        print(";")
        print()