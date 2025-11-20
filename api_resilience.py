"""
API Resilience: Retry logic, exponential backoff, session management.
"""

import time
import logging
from typing import TypeVar, Callable, Any, Optional
import requests


T = TypeVar('T')


class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0  # seconds
    backoff_factor: float = 2.0
    timeout: int = 10  # seconds


def exponential_backoff_retry(func: Callable[..., T], config: Optional[RetryConfig] = None) -> T:
    """
    Retry a function call with exponential backoff.
    
    Args:
        func: Callable to execute
        config: RetryConfig for retry behavior
    
    Returns:
        Function result
    
    Raises:
        Exception: If all retries exhausted
    """
    config = config or RetryConfig()
    logger = logging.getLogger(__name__)
    
    last_exception = None
    delay = config.base_delay
    
    for attempt in range(config.max_retries + 1):
        try:
            return func()
        except (requests.exceptions.Timeout, 
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError) as e:
            last_exception = e
            
            if attempt == config.max_retries:
                logger.error(f"Max retries ({config.max_retries}) exhausted for {func.__name__}")
                raise
            
            logger.warning(f"Attempt {attempt + 1}/{config.max_retries + 1} failed: {e}. "
                         f"Retrying in {delay:.1f}s...")
            time.sleep(delay)
            delay = min(delay * config.backoff_factor, config.max_delay)
    
    # Should not reach here, but just in case
    raise last_exception or Exception("Retry failed unexpectedly")


class ResilientSession:
    """HTTP session with retry logic and timeouts."""
    
    def __init__(self, retry_config: Optional[RetryConfig] = None):
        self.session = requests.Session()
        self.retry_config = retry_config or RetryConfig()
        self.logger = logging.getLogger(__name__)
    
    def request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make request with retry logic."""
        # Ensure timeout
        if 'timeout' not in kwargs:
            kwargs['timeout'] = self.retry_config.timeout
        
        def _make_request():
            return self.session.request(method, url, **kwargs)
        
        return exponential_backoff_retry(_make_request, self.retry_config)
    
    def get(self, url: str, **kwargs) -> requests.Response:
        return self.request('GET', url, **kwargs)
    
    def post(self, url: str, **kwargs) -> requests.Response:
        return self.request('POST', url, **kwargs)
    
    def put(self, url: str, **kwargs) -> requests.Response:
        return self.request('PUT', url, **kwargs)
    
    def delete(self, url: str, **kwargs) -> requests.Response:
        return self.request('DELETE', url, **kwargs)
    
    def close(self):
        """Close session."""
        self.session.close()
