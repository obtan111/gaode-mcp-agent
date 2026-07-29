import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from queue import Queue

from src.database import get_supabase_client, CircuitBreaker, ALL_SCHEMAS_SQL
from src.database.supabase_client import SupabaseClient


def reset_supabase_singleton():
    SupabaseClient._instance = None
    if hasattr(SupabaseClient, '_initialized'):
        delattr(SupabaseClient, '_initialized')


class TestCircuitBreaker:
    def test_circuit_breaker_closed_state(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        
        def success_func():
            return "success"
        
        result = breaker.call(success_func)
        assert result == "success"
        assert breaker._state == "closed"

    def test_circuit_breaker_trips_after_failures(self):
        breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)
        
        def fail_func():
            raise ValueError("always fails")
        
        for _ in range(3):
            with pytest.raises(ValueError):
                breaker.call(fail_func)
        
        assert breaker._state == "open"
        
        with pytest.raises(ConnectionError):
            breaker.call(fail_func)

    def test_circuit_breaker_recovers_after_timeout(self):
        breaker = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5)
        
        def fail_func():
            raise ValueError("fails")
        
        for _ in range(2):
            with pytest.raises(ValueError):
                breaker.call(fail_func)
        
        assert breaker._state == "open"
        
        time.sleep(0.6)
        
        def success_func():
            return "recovered"
        
        result = breaker.call(success_func)
        assert result == "recovered"
        assert breaker._state == "closed"


class TestSupabaseClient:
    @patch('src.database.supabase_client.create_client')
    def test_client_pool_initialization(self, mock_create_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_create_client.return_value = mock_client
        
        os.environ["SUPABASE_URL"] = "https://test.supabase.co"
        os.environ["SUPABASE_KEY"] = "test-key"
        os.environ["CONNECTION_POOL_SIZE"] = "2"
        
        client = get_supabase_client()
        
        assert mock_create_client.call_count == 2
        
        client.shutdown()
        reset_supabase_singleton()

    @patch('src.database.supabase_client.create_client')
    def test_get_client_from_pool(self, mock_create_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_create_client.return_value = mock_client
        
        os.environ["SUPABASE_URL"] = "https://test.supabase.co"
        os.environ["SUPABASE_KEY"] = "test-key"
        os.environ["CONNECTION_POOL_SIZE"] = "1"
        
        client = get_supabase_client()
        
        retrieved = client.get_client()
        
        client.release_client(retrieved)
        
        retrieved_again = client.get_client()
        assert retrieved_again is not None
        
        client.shutdown()
        reset_supabase_singleton()

    @patch('src.database.supabase_client.create_client')
    def test_execute_with_client(self, mock_create_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_create_client.return_value = mock_client
        
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_select = Mock()
        mock_table.select.return_value = mock_select
        mock_select.execute.return_value = Mock(data=[], count=0)
        
        os.environ["SUPABASE_URL"] = "https://test.supabase.co"
        os.environ["SUPABASE_KEY"] = "test-key"
        os.environ["CONNECTION_POOL_SIZE"] = "1"
        
        client = get_supabase_client()
        
        result = client.execute_with_client(lambda c: c.table("documents").select("*").execute())
        
        assert result is not None
        mock_client.table.assert_called_with("documents")
        
        client.shutdown()
        reset_supabase_singleton()


class TestSchemaSQL:
    def test_all_schemas_sql_contains_extensions(self):
        assert "CREATE EXTENSION" in ALL_SCHEMAS_SQL
        assert "pgvector" in ALL_SCHEMAS_SQL
        assert "pg_trgm" in ALL_SCHEMAS_SQL

    def test_all_schemas_sql_contains_tables(self):
        assert "CREATE TABLE" in ALL_SCHEMAS_SQL
        assert "documents" in ALL_SCHEMAS_SQL
        assert "chat_session" in ALL_SCHEMAS_SQL
        assert "mcp_call_log" in ALL_SCHEMAS_SQL
        assert "travel_plan" in ALL_SCHEMAS_SQL

    def test_documents_table_has_vector_column(self):
        assert "vector vector(1536)" in ALL_SCHEMAS_SQL

    def test_indexes_are_created(self):
        assert "CREATE INDEX" in ALL_SCHEMAS_SQL
        assert "idx_documents_vector" in ALL_SCHEMAS_SQL
        assert "vector_cosine_ops" in ALL_SCHEMAS_SQL


if __name__ == "__main__":
    pytest.main([__file__, "-v"])