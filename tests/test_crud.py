import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import Mock, patch
from uuid import UUID

from src.database.crud import (
    insert_document,
    search_documents_by_vector,
    search_documents_by_keyword,
    delete_document_by_id,
    delete_documents_by_filename,
    get_documents_by_kb,
    create_session,
    get_session_by_id,
    update_session,
    delete_session,
    list_sessions,
    log_mcp_call,
    get_logs_by_session,
    get_logs_by_tool,
    create_travel_plan,
    get_travel_plan_by_id,
    update_travel_plan,
    delete_travel_plan,
    list_travel_plans,
)
from src.database.supabase_client import SupabaseClient
from src.rag.text_splitter import TextSplitter


def reset_supabase_singleton():
    SupabaseClient._instance = None
    if hasattr(SupabaseClient, '_initialized'):
        delattr(SupabaseClient, '_initialized')


class TestDocumentsCRUD:
    @patch('src.database.crud.get_supabase_client')
    def test_insert_document(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_table = Mock()
        mock_client.execute_with_client.return_value = {"id": "test-uuid", "content": "test content"}
        
        result = insert_document(
            content="test content",
            vector=[0.1] * 1536,
            filename="test.pdf",
            page_number=1,
            category="test",
            kb_name="test_kb"
        )
        
        assert result is not None
        assert result["id"] == "test-uuid"
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_search_documents_by_vector(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = [{"id": "1", "content": "test"}]
        
        results = search_documents_by_vector(
            query_vector=[0.1] * 1536,
            limit=5,
            kb_name="test_kb"
        )
        
        assert len(results) == 1
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    @patch('src.database.crud.get_documents_by_kb')
    def test_insert_document_skips_duplicate_content_hash(self, mock_get_documents_by_kb, mock_get_client):
        reset_supabase_singleton()

        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_get_documents_by_kb.return_value = [{
            "id": "existing-id",
            "content": "same content",
            "metadata": {"content_hash": "abc123"},
        }]

        result = insert_document(
            content="same content",
            vector=[0.1] * 8,
            filename="test.txt",
            metadata={"content_hash": "abc123"},
            kb_name="test_kb",
        )

        assert result is None
        mock_client.execute_with_client.assert_not_called()

        reset_supabase_singleton()

    def test_text_splitter_adds_content_hash_metadata(self):
        splitter = TextSplitter()
        chunks = splitter.split(
            text="这是一个测试文档，包含足够长的内容来生成多个切片。" * 6,
            file_name="test.txt",
            file_type="txt",
            category="test",
        )

        assert chunks
        assert all("content_hash" in chunk["metadata"] for chunk in chunks)

    @patch('src.database.crud.get_supabase_client')
    def test_search_documents_by_keyword(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = [{"id": "1", "content": "test keyword"}]
        
        results = search_documents_by_keyword(
            keyword="test",
            limit=5,
            kb_name="test_kb"
        )
        
        assert len(results) == 1
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_delete_documents_by_filename(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = 2
        
        count = delete_documents_by_filename("test.pdf")
        
        assert count == 2
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()


class TestChatSessionCRUD:
    @patch('src.database.crud.get_supabase_client')
    def test_create_session(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = {"id": "session-uuid", "title": "Test Session"}
        
        result = create_session(
            title="Test Session",
            summary="Test summary",
            messages=[{"role": "user", "content": "Hello"}]
        )
        
        assert result is not None
        assert result["title"] == "Test Session"
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_list_sessions(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = [
            {"id": "1", "title": "Session 1"},
            {"id": "2", "title": "Session 2"}
        ]
        
        results = list_sessions(page=1, page_size=10)
        
        assert len(results) == 2
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_update_session(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        mock_client.execute_with_client.return_value = {
            "id": "session-uuid",
            "title": "Updated Session",
            "messages": [{"role": "user", "content": "Hello"}]
        }
        
        result = update_session(
            session_id=UUID("12345678-1234-5678-1234-567812345678"),
            title="Updated Session",
            append_message={"role": "assistant", "content": "Hi"}
        )
        
        assert result is not None
        assert result["title"] == "Updated Session"
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()


class TestMCPLogCRUD:
    @patch('src.database.crud.get_supabase_client')
    def test_log_mcp_call(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = {"id": "log-uuid", "tool_name": "TimeMCP"}
        
        result = log_mcp_call(
            tool_name="TimeMCP",
            parameters={"query": "now"},
            result={"time": "2024-01-01"},
            token_usage=100,
            session_id=UUID("12345678-1234-5678-1234-567812345678")
        )
        
        assert result is not None
        assert result["tool_name"] == "TimeMCP"
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_get_logs_by_session(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = [
            {"id": "1", "tool_name": "TimeMCP"},
            {"id": "2", "tool_name": "AmapMCP"}
        ]
        
        results = get_logs_by_session(
            session_id=UUID("12345678-1234-5678-1234-567812345678"),
            limit=10
        )
        
        assert len(results) == 2
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()


class TestTravelPlanCRUD:
    @patch('src.database.crud.get_supabase_client')
    def test_create_travel_plan(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = {
            "id": "plan-uuid",
            "title": "Beijing Trip",
            "destination": "Beijing",
            "days": 3
        }
        
        result = create_travel_plan(
            title="Beijing Trip",
            destination="Beijing",
            days=3,
            budget=5000.0,
            plan_data={"day1": "Forbidden City"},
            weather_info={"city": "Beijing", "forecast": "sunny"}
        )
        
        assert result is not None
        assert result["destination"] == "Beijing"
        assert result["days"] == 3
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_list_travel_plans(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = [
            {"id": "1", "title": "Trip 1", "destination": "Beijing"},
            {"id": "2", "title": "Trip 2", "destination": "Shanghai"}
        ]
        
        results = list_travel_plans(page=1, page_size=10)
        
        assert len(results) == 2
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()

    @patch('src.database.crud.get_supabase_client')
    def test_update_travel_plan(self, mock_get_client):
        reset_supabase_singleton()
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_client.execute_with_client.return_value = {
            "id": "plan-uuid",
            "title": "Updated Trip",
            "days": 5
        }
        
        result = update_travel_plan(
            plan_id=UUID("12345678-1234-5678-1234-567812345678"),
            title="Updated Trip",
            days=5
        )
        
        assert result is not None
        assert result["days"] == 5
        mock_client.execute_with_client.assert_called_once()
        
        reset_supabase_singleton()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])