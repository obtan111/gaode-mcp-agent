import time
import functools
from typing import Callable, Any, Tuple, Type


def retry(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    initial_delay: float = 1.0,
    retry_on_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    timeout: float = None,
) -> Callable:
    """
    重试装饰器，支持指数退避、超时和异常过滤。

    参数：
    - max_retries: 最大重试次数（不含首次调用）
    - backoff_factor: 退避因子，每次重试延迟 = initial_delay * (backoff_factor ** attempt)
    - initial_delay: 初始重试延迟（秒）
    - retry_on_exceptions: 仅当抛出这些异常时才重试，其他异常直接抛出
    - timeout: 总超时时间（秒），超过后抛出 TimeoutError，None 表示不设超时

    使用示例：
        @retry(max_retries=3, backoff_factor=2.0)
        def fetch_data(url):
            ...

        @retry(max_retries=2, retry_on_exceptions=(ConnectionError, TimeoutError))
        def connect():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception = None
            delay = initial_delay
            start_time = time.time()

            for attempt in range(max_retries + 1):
                if timeout is not None:
                    elapsed = time.time() - start_time
                    if elapsed >= timeout:
                        raise TimeoutError(f"{func.__name__} timed out after {timeout}s")

                try:
                    return func(*args, **kwargs)
                except retry_on_exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        time.sleep(delay)
                        delay *= backoff_factor

            if last_exception:
                raise last_exception

        return wrapper

    return decorator
