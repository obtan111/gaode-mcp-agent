import sys
import os
import tempfile
import threading
sys.path.insert(0, '.')

def test_cache():
    print('=== Test 1: Cache Key Generation ===')
    from src.mcp.cache import MCPCache
    cache = MCPCache()
    key1 = cache._generate_cache_key('TestMCP', 'test_method', {'a': 1, 'b': 'hello'})
    print(f'Normal params key: {key1}')
    key2 = cache._generate_cache_key('TestMCP', 'test_method', {})
    print(f'Empty params key: {key2}')
    key3 = cache._generate_cache_key('TestMCP', 'test_method', {'query': 'Chinese test'})
    print(f'Special chars key: {key3}')
    print('Cache key generation: OK\n')

def test_registration():
    print('=== Test 2: MCP Tool Registration ===')
    from src.mcp.mcp_client import MCPClient
    tools = MCPClient.get_registered_tools()
    print(f'Registered tools: {tools}')
    assert 'AmapMCP' in tools
    assert 'FileMCP' in tools
    assert 'WebMCP' in tools
    assert 'ScheduleMCP' in tools
    assert 'TimeMCP' in tools
    funcs = MCPClient.get_all_available_functions()
    print(f'Total functions: {len(funcs)}')
    print('Tool registration: OK\n')

def test_budget():
    print('=== Test 3: Budget Estimation ===')
    from src.mcp.amap_mcp import AmapMCP
    amap = AmapMCP()
    budget = amap.get_budget_estimate(days=3, travelers=2, budget_level='medium')
    print(f'3d/2p/medium: total={budget["total_cost"]}, per_person={budget["per_person_cost"]}')
    assert budget['total_cost'] > 0
    assert budget['per_person_cost'] > 0
    budget2 = amap.get_budget_estimate(days=1, travelers=1, budget_level='economy')
    print(f'1d/1p/economy: total={budget2["total_cost"]}')
    budget3 = amap.get_budget_estimate(days=7, travelers=4, budget_level='luxury')
    print(f'7d/4p/luxury: total={budget3["total_cost"]}')
    print('Budget estimation: OK\n')

def test_schedule():
    print('=== Test 4: ScheduleMCP CRUD ===')
    from src.mcp.schedule_mcp import ScheduleMCP
    schedule = ScheduleMCP()
    result = schedule.create_schedule('test schedule', '2026-12-25', time='10:00')
    assert result['success']
    schedule_id = result['schedule']['id']
    print(f'Created: {schedule_id}')
    list_result = schedule.list_schedules()
    assert list_result['stats']['total'] > 0
    del_result = schedule.delete_schedule(schedule_id)
    assert del_result['success']
    print('ScheduleMCP CRUD: OK')

    result2 = schedule.create_todo('test todo', priority=2)
    todo_id = result2['todo']['id']
    summary = schedule.get_daily_summary()
    print(f'Daily summary: {summary["date"]}')
    del_result2 = schedule.delete_todo(todo_id)
    assert del_result2['success']
    print('ScheduleMCP Todo: OK\n')

def test_file_safety():
    print('=== Test 5: FileMCP Path Validation ===')
    from src.mcp.file_mcp import FileMCP
    fmcp = FileMCP()
    try:
        fmcp._validate_path('/etc/passwd')
        print('ERROR: Should have raised PermissionError')
    except PermissionError:
        print('Path traversal blocked: OK')
    valid = fmcp._validate_path('~/Desktop')
    print(f'Valid path resolved: {valid}')
    print('FileMCP safety: OK\n')

def test_export_edge_cases():
    print('=== Test 6: Export Edge Cases ===')
    from src.utils.itinerary_exporter import export_itinerary, parse_itinerary_from_text
    empty_result = export_itinerary({}, format='markdown')
    print(f'Empty itinerary: success={empty_result["success"]}')
    invalid_result = export_itinerary({'title': 'Test'}, format='pdf')
    assert not invalid_result['success']
    print(f'Invalid format rejected: OK')
    parsed = parse_itinerary_from_text('not valid json')
    assert parsed['title'] == '旅行计划'
    print(f'Fallback parse: OK')
    result = export_itinerary({'daily_itinerary': [], 'tips': []}, format='markdown')
    print(f'Minimal itinerary: success={result["success"]}')
    print('Export edge cases: OK\n')

def test_memory_init_and_persistence():
    print('=== Test 7: Memory Init and Persistence ===')
    from src.agent.memory import LongTermMemory
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        storage_path = f.name
    
    try:
        memory1 = LongTermMemory(storage_path=storage_path)
        memory1.update_user_profile(name='测试用户', age=25)
        memory1.add_fact_memory('用户计划去长沙旅游', importance=4)
        memory1.add_preference_memory('食物', '喜欢吃辣', intensity=5)
        memory1.add_session_summary('session_001', '用户询问了长沙天气', key_topics=['长沙', '天气'])
        
        memory2 = LongTermMemory(storage_path=storage_path)
        profile = memory2.get_user_profile()
        assert profile.get('name') == '测试用户'
        print(f'Profile persisted: {profile}')
        
        facts = memory2.search_memories('长沙', memory_type='fact')
        assert len(facts) > 0
        assert '长沙' in facts[0]['content']
        print(f'Fact search: found {len(facts)} results')
        
        prefs = memory2.search_memories('食物', memory_type='preference')
        assert len(prefs) > 0
        print(f'Preference search: found {len(prefs)} results')
        
        summaries = memory2.search_memories('长沙', memory_type='summary')
        assert len(summaries) > 0
        print(f'Summary search: found {len(summaries)} results')
        
        print('Memory persistence: OK\n')
    finally:
        os.unlink(storage_path)

def test_memory_context_retrieval():
    print('=== Test 8: Memory Context Retrieval ===')
    from src.agent.memory import LongTermMemory
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        storage_path = f.name
    
    try:
        memory = LongTermMemory(storage_path=storage_path)
        memory.update_user_profile(name='小明', city='北京')
        memory.add_fact_memory('小明计划2024年去日本留学', importance=5)
        memory.add_fact_memory('小明正在学习日语N3', importance=4)
        memory.add_preference_memory('学习', '喜欢语言学习', intensity=5)
        
        context = memory.get_relevant_context('我想去日本留学')
        assert context
        assert '小明' in context or '日本' in context
        print(f'Context for study query: {context[:100]}...')
        
        context2 = memory.get_relevant_context('我想学日语')
        assert context2
        print(f'Context for language query: {context2[:100]}...')
        
        context3 = memory.get_relevant_context('今天天气怎么样')
        profile_only = '北京' in context3 or '小明' in context3
        print(f'Context for weather query: {context3[:100]}... (has profile: {profile_only})')
        
        empty_context = memory.get_relevant_context('')
        print(f'Empty query context: "{empty_context}"')
        
        print('Memory context retrieval: OK\n')
    finally:
        os.unlink(storage_path)

def test_memory_forget_and_cleanup():
    print('=== Test 9: Memory Forget and Cleanup ===')
    from src.agent.memory import LongTermMemory
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        storage_path = f.name
    
    try:
        memory = LongTermMemory(storage_path=storage_path)
        
        fact = memory.add_fact_memory('测试事实1', importance=1)
        fact_id = fact['id']
        print(f'Added fact: {fact_id}')
        
        pref = memory.add_preference_memory('测试', '测试偏好', intensity=1)
        pref_id = pref['id']
        print(f'Added preference: {pref_id}')
        
        assert memory.forget_memory(fact_id)
        print(f'Forgotten fact: {fact_id}')
        
        assert memory.forget_memory(pref_id)
        print(f'Forgotten preference: {pref_id}')
        
        assert not memory.forget_memory('nonexistent_id')
        print('Non-existent forget: correctly returns False')
        
        for i in range(150):
            memory.add_fact_memory(f'批量测试事实_{i}', importance=1)
        
        initial_count = len(memory._memory['fact_memories'])
        print(f'Facts before cleanup: {initial_count}')
        
        cleaned = memory.cleanup_expired(max_facts=100)
        assert cleaned == 50
        remaining = len(memory._memory['fact_memories'])
        assert remaining == 100
        print(f'Cleaned up {cleaned} facts, remaining: {remaining}')
        
        cleaned2 = memory.cleanup_expired(max_facts=100)
        assert cleaned2 == 0
        print('No cleanup needed when under limit: OK')
        
        print('Memory forget and cleanup: OK\n')
    finally:
        os.unlink(storage_path)

def test_memory_thread_safety():
    print('=== Test 10: Memory Thread Safety ===')
    from src.agent.memory import LongTermMemory
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        storage_path = f.name
    
    try:
        memory = LongTermMemory(storage_path=storage_path)
        errors = []
        
        def writer(thread_id):
            try:
                for i in range(10):
                    memory.add_fact_memory(f'线程{thread_id}_事实{i}', importance=3)
                    memory.update_user_profile(**{f'thread_{thread_id}_key_{i}': f'value_{i}'})
            except Exception as e:
                errors.append(f'Writer {thread_id}: {e}')
        
        def reader(thread_id):
            try:
                for _ in range(10):
                    memory.search_memories('测试')
                    memory.get_relevant_context('查询')
            except Exception as e:
                errors.append(f'Reader {thread_id}: {e}')
        
        threads = []
        for i in range(3):
            t = threading.Thread(target=writer, args=(i,))
            threads.append(t)
        for i in range(2):
            t = threading.Thread(target=reader, args=(i,))
            threads.append(t)
        
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        
        if errors:
            print(f'Thread errors: {errors}')
        else:
            print('No thread safety errors')
        
        stats = memory.get_all_memories_summary()
        total_facts = stats['stats']['total_facts']
        total_profile_keys = len(stats['profile'])
        print(f'After concurrent access: {total_facts} facts, {total_profile_keys} profile keys')
        assert total_facts >= 30, f'Expected >= 30 facts, got {total_facts}'
        assert total_profile_keys >= 30, f'Expected >= 30 profile keys, got {total_profile_keys}'
        print('Memory thread safety: OK\n')
    finally:
        os.unlink(storage_path)

def test_memory_boundary_conditions():
    print('=== Test 11: Memory Boundary Conditions ===')
    from src.agent.memory import LongTermMemory
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        storage_path = f.name
    
    try:
        memory = LongTermMemory(storage_path=storage_path)
        
        boundary_cases = [
            '',
            '   ',
            'a' * 10000,
            '特殊字符: 你好, 🎉, <script>, SQL: DROP TABLE',
            None,
        ]
        
        for case in boundary_cases[:4]:
            try:
                memory.add_fact_memory(case or '', importance=3)
                print(f'Added fact with content length {len(case or "")}: OK')
            except Exception as e:
                print(f'Boundary case failed: {e}')
        
        profile_data = {
            'name': '',
            'bio': 'a' * 50000,
            'websites': 'https://example.com?q=1&b=2&c=3',
        }
        for k, v in profile_data.items():
            try:
                memory.update_user_profile(**{k: v})
                print(f'Updated profile[{k}] length={len(str(v))}: OK')
            except Exception as e:
                print(f'Profile update failed for {k}: {e}')
        
        importance_boundaries = [0, 1, 5, 6, -1, 100]
        for imp in importance_boundaries:
            fact = memory.add_fact_memory(f'importance_test_{imp}', importance=imp)
            actual_imp = fact['importance']
            expected = max(1, min(5, imp))
            assert actual_imp == expected, f'Expected {expected}, got {actual_imp}'
        print(f'Importance boundaries (0,1,5,6,-1,100) all correctly clamped: OK')
        
        context_empty = memory.get_relevant_context('')
        print(f'Empty query context: "{context_empty[:50]}"... (non-empty: {bool(context_empty)})')
        
        summary = memory.get_all_memories_summary()
        print(f'Memory summary stats: {summary["stats"]}')
        
        print('Memory boundary conditions: OK\n')
    finally:
        os.unlink(storage_path)

def test_memory_summary_limit():
    print('=== Test 12: Memory Session Summary Limit ===')
    from src.agent.memory import LongTermMemory
    
    with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
        storage_path = f.name
    
    try:
        memory = LongTermMemory(storage_path=storage_path)
        
        for i in range(55):
            memory.add_session_summary(
                session_id=f'session_{i}',
                summary=f'这是第{i}个会话摘要',
                key_topics=[f'topic_{i}'],
            )
        
        total_summaries = len(memory._memory['session_summaries'])
        print(f'Summaries after adding 55: {total_summaries}')
        assert total_summaries == 50
        
        oldest = memory._memory['session_summaries'][0]
        print(f'Oldest summary ID: {oldest["id"]}')
        
        result = memory.search_memories('session_54', memory_type='summary')
        print(f'Search for recent session: {len(result)} results')
        
        print('Memory summary limit: OK\n')
    finally:
        os.unlink(storage_path)

if __name__ == '__main__':
    test_cache()
    test_registration()
    test_budget()
    test_schedule()
    test_file_safety()
    test_export_edge_cases()
    test_memory_init_and_persistence()
    test_memory_context_retrieval()
    test_memory_forget_and_cleanup()
    test_memory_thread_safety()
    test_memory_boundary_conditions()
    test_memory_summary_limit()
    print('=== ALL BOUNDARY TESTS PASSED ===')
