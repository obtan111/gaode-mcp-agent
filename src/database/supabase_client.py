import threading
import time
from typing import Optional, List
from queue import Queue, Empty

from supabase import create_client, Client
from src.config.settings import Config
from src.database.schema import ALL_SCHEMAS_SQL
from src.database.pgvector_state import set_pgvector_available
from src.utils.logger import setup_logger
from src.utils.retry import retry

logger = setup_logger("supabase_client")


class CircuitBreaker:
    """
    断路器模式实现，用于数据库连接的故障容错。
    
    断路器状态：
    - closed: 正常状态，允许所有请求通过
    - open: 打开状态，拒绝所有请求，等待恢复时间
    - half-open: 半开状态，允许少量请求测试服务是否恢复
    
    工作原理：
    1. 当连续失败次数达到阈值时，断路器打开
    2. 打开后等待 recovery_timeout 时间
    3. 超时后进入半开状态，尝试执行请求
    4. 如果成功，断路器关闭；如果失败，重新打开
    
    参数：
    - failure_threshold: 触发断路器打开的失败次数阈值，默认 5
    - recovery_timeout: 断路器打开后的恢复等待时间（秒），默认 30
    - logger: 日志记录器
    """
    def __init__(
        self,
        failure_threshold: int = 10,
        recovery_timeout: float = 15.0,
        logger=logger,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.logger = logger
        self._lock = threading.Lock()
        self._failures = 0
        self._last_failure_time = 0.0
        self._state = "closed"

    def call(self, func, *args, **kwargs):
        should_attempt = True
        with self._lock:
            if self._state == "open":
                elapsed = time.time() - self._last_failure_time
                if elapsed >= self.recovery_timeout:
                    self._state = "half-open"
                    self.logger.info("Circuit breaker transitioning to half-open state")
                else:
                    should_attempt = False
            prev_state = self._state

        if not should_attempt:
            raise ConnectionError(
                f"Circuit breaker is open, try again in {self.recovery_timeout - (time.time() - self._last_failure_time):.1f}s"
            )

        try:
            result = func(*args, **kwargs)
            with self._lock:
                self._failures = 0
                self._state = "closed"
            return result
        except Exception as e:
            with self._lock:
                self._failures += 1
                self._last_failure_time = time.time()
                if self._failures >= self.failure_threshold:
                    self._state = "open"
                    self.logger.error(f"Circuit breaker tripped after {self._failures} failures")
                elif prev_state == "half-open":
                    self._state = "open"
                    self.logger.error("Circuit breaker re-tripped from half-open state")
            raise


class SupabaseClient:
    """
    Supabase 客户端管理类，实现连接池、心跳检测和断路器功能。
    
    采用单例模式确保全局只有一个实例，管理多个数据库连接。
    
    核心功能：
    1. 连接池管理：维护多个 Supabase 客户端连接
    2. 断路器保护：防止频繁失败请求对数据库造成压力
    3. 心跳检测：定期检查连接健康状态，自动重建失效连接
    4. 表初始化检查：验证数据库表是否存在
    
    使用方法：
    ```python
    client = get_supabase_client()
    result = client.execute_with_client(lambda sb: sb.table("...").select("*").execute())
    ```
    """
    
    _instance = None  # 单例实例
    _lock = threading.Lock()  # 线程锁，保证单例线程安全

    def __new__(cls, *args, **kwargs):
        """实现单例模式，确保全局只有一个实例"""
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(SupabaseClient, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化 Supabase 客户端管理类"""
        # 防止重复初始化
        if hasattr(self, "_initialized"):
            return

        # 加载配置
        self.config = Config()
        self.pool_size = self.config.CONNECTION_POOL_SIZE
        self.connection_timeout = self.config.CONNECTION_TIMEOUT
        self.heartbeat_interval = self.config.HEARTBEAT_INTERVAL

        # 初始化连接池、断路器和心跳线程
        self._client_pool: Queue[Client] = Queue(maxsize=self.pool_size)
        self._circuit_breaker = CircuitBreaker()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_running = False

        # 执行初始化步骤
        self._init_pool()      # 初始化连接池（同步）
        self._start_heartbeat()# 启动心跳检测（后台线程）
        
        # 将表检查和初始化移到后台线程，避免阻塞应用启动
        import threading
        init_thread = threading.Thread(target=self._init_tables, daemon=True)
        init_thread.start()

        self._initialized = True

    def _create_client(self) -> Client:
        """
        创建一个新的 Supabase 客户端连接。
        
        从配置中获取 URL 和 Key，创建并返回客户端实例。
        
        返回：
        - Supabase Client 实例
        
        异常：
        - ValueError: 如果 SUPABASE_URL 或 SUPABASE_KEY 未设置
        """
        url = self.config.SUPABASE_URL
        key = self.config.SUPABASE_KEY

        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set")

        return create_client(url, key)

    def _init_pool(self):
        """初始化连接池，创建3个初始连接，其余按需创建"""
        for _ in range(min(3, self.pool_size)):
            try:
                client = self._create_client()
                self._client_pool.put(client)
                logger.info("Supabase client added to pool")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {str(e)}")

    def _init_tables(self):
        """
        检查表是否存在，并检测 pgvector 扩展可用性。
        
        检查流程：
        1. 尝试查询 chat_session 表，如果成功说明表已存在
        2. 尝试查询 documents 表，检测 pgvector 是否可用
        3. 设置 pgvector 全局状态，供其他模块使用
        
        如果表不存在，需要在 Supabase Dashboard 中手动创建。
        """
        pgvector_available = True
        try:
            client = self.get_client()
            
            def check_with_timeout(func, timeout=10):
                import threading
                
                class TimeoutError(Exception):
                    pass
                
                result = None
                exception = None
                
                def worker():
                    nonlocal result, exception
                    try:
                        result = func()
                    except Exception as e:
                        exception = e
                
                thread = threading.Thread(target=worker, daemon=True)
                thread.start()
                thread.join(timeout=timeout)
                
                if thread.is_alive():
                    raise TimeoutError("Operation timed out")
                
                if exception:
                    raise exception
                
                return result
            
            try:
                result = check_with_timeout(
                    lambda: client.table("chat_session").select("id").limit(1).execute(),
                    timeout=5
                )
                logger.info("Tables already exist")
            except Exception as e:
                logger.info(f"Tables may not exist yet or timeout: {str(e)}")

            try:
                result = check_with_timeout(
                    lambda: client.table("documents").select("id").limit(1).execute(),
                    timeout=5
                )
                pgvector_available = True
            except Exception:
                pgvector_available = False
                logger.info("Documents table not found or pgvector not available, using JSONB fallback")

        except Exception as e:
            logger.warning(f"Failed to check table existence: {str(e)}. Please ensure tables are created in Supabase Dashboard.")

        logger.info("Database tables check completed. pgvector available: %s", pgvector_available)
        set_pgvector_available(pgvector_available)

    @retry(max_retries=3, backoff_factor=2.0, initial_delay=1.0, timeout=30.0)
    def _ping_client(self, client: Client) -> bool:
        """
        检查客户端连接是否健康。
        
        通过执行简单查询来检测连接状态：
        1. 尝试查询 documents 表
        2. 如果失败，尝试调用 echo RPC
        
        参数：
        - client: Supabase 客户端实例
        
        返回：
        - True: 连接健康
        - False: 连接失效
        """
        try:
            result = client.table("documents").select("id").limit(1).execute()
            return True
        except Exception:
            try:
                result = client.rpc("echo", {"message": "ping"}).execute()
                return True
            except Exception:
                return False

    def _start_heartbeat(self):
        """启动心跳检测线程，定期检查连接池中的所有连接"""
        def heartbeat():
            while self._heartbeat_running:
                time.sleep(self.heartbeat_interval)
                self._perform_heartbeat()

        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        self._heartbeat_thread.start()
        logger.info("Heartbeat thread started")

    def _perform_heartbeat(self):
        """
        执行心跳检测：检查连接池中所有客户端的健康状态。
        
        检测流程：
        1. 从连接池中取出所有客户端
        2. 对每个客户端执行 ping 检测
        3. 如果 ping 失败，重新创建客户端
        4. 将客户端放回连接池
        """
        clients_to_check: List[Client] = []
        while True:
            try:
                clients_to_check.append(self._client_pool.get_nowait())
            except Empty:
                break

        for client in clients_to_check:
            try:
                if not self._ping_client(client):
                    logger.warning("Client ping failed, recreating...")
                    client = self._create_client()
                self._client_pool.put(client)
            except Exception as e:
                logger.error(f"Heartbeat failed for client: {str(e)}")
                try:
                    client = self._create_client()
                    self._client_pool.put(client)
                except Exception as recreate_error:
                    logger.error(f"Failed to recreate client: {str(recreate_error)}")

    def get_client(self) -> Client:
        """
        从连接池获取一个客户端连接。
        
        如果连接池为空，会立即创建新的客户端（使用短超时避免阻塞）。
        
        返回：
        - Supabase Client 实例
        
        异常：
        - 如果连接池为空且创建新客户端失败，会抛出异常
        """
        try:
            client = self._client_pool.get_nowait()
            return client
        except Empty:
            logger.debug("Client pool empty, creating new client")
            return self._create_client()

    def release_client(self, client: Client):
        """
        将客户端连接放回连接池。
        
        参数：
        - client: 使用完毕的 Supabase 客户端实例
        """
        try:
            self._client_pool.put(client, block=False)
        except Exception:
            pass

    @retry(max_retries=2, backoff_factor=1.0, initial_delay=0.3, timeout=15.0)
    def execute_with_client(self, func):
        """
        使用连接池中的客户端执行数据库操作。
        
        核心流程：
        1. 从连接池获取客户端
        2. 通过断路器执行操作
        3. 无论成功或失败，都将客户端放回连接池
        4. 支持自动重试（最多 3 次）
        
        参数：
        - func: 接受一个 Supabase Client 参数的函数
        
        返回：
        - func 执行的返回值
        """
        client = self.get_client()
        try:
            return self._circuit_breaker.call(func, client)
        finally:
            self.release_client(client)

    def shutdown(self):
        """关闭客户端管理，停止心跳线程"""
        self._heartbeat_running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)


def get_supabase_client() -> SupabaseClient:
    """
    获取 Supabase 客户端管理类的单例实例。
    
    返回：
    - SupabaseClient 单例实例
    """
    return SupabaseClient()