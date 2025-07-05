"""
Token usage tracking utility for capturing LLM token consumption
across the chat processing pipeline.
"""
from typing import Dict, Any, Optional
from threading import local
import threading
import time


class TokenUsageTracker:
    """Thread-local storage for tracking token usage during chat processing."""
    
    def __init__(self):
        self._local = local()
        # Non-thread-local storage for cross-thread access
        self._global_storage = {}
        self._storage_lock = threading.Lock()
    
    def set_usage(self, usage_data: Dict[str, Any]) -> None:
        """Store token usage data for the current thread/request."""
        # Don't overwrite existing valid usage data with None/empty data
        # This prevents tool selection LLM calls from clearing the main chat LLM usage
        current_usage = getattr(self._local, 'usage_data', None)
        if current_usage is not None and usage_data is None:
            return
            
        # Don't overwrite larger token usage with smaller usage
        # This prevents tool selection LLM calls from overwriting main chat LLM usage
        if (current_usage is not None and usage_data is not None and
            'total_tokens' in current_usage and 'total_tokens' in usage_data):
            if usage_data['total_tokens'] < current_usage['total_tokens']:
                from onyx.utils.logger import setup_logger
                logger = setup_logger()
                logger.info(f"[TOKEN_TRACKER] Preventing overwrite of larger usage {current_usage['total_tokens']} with smaller usage {usage_data['total_tokens']}")
                return
            
        self._local.usage_data = usage_data
        
        # Also store globally with a timestamp for cross-thread access
        current_time = time.time()
        thread_id = threading.get_ident()
        key = f"{thread_id}_{current_time}"
        
        with self._storage_lock:
            # Store with timestamp for cleanup
            self._global_storage[key] = {
                'usage_data': usage_data, 
                'timestamp': current_time,
                'thread_id': thread_id
            }
            # Clean up old entries (older than 60 seconds)
            cutoff_time = current_time - 60
            keys_to_remove = [k for k, v in self._global_storage.items() if v['timestamp'] < cutoff_time]
            for k in keys_to_remove:
                del self._global_storage[k]
    
    def get_usage(self) -> Optional[Dict[str, Any]]:
        """Retrieve token usage data for the current thread/request."""
        return getattr(self._local, 'usage_data', None)
    
    def get_latest_usage(self) -> Optional[Dict[str, Any]]:
        """Get the most recent token usage from any thread."""
        with self._storage_lock:
            if not self._global_storage:
                return None
            
            # Find the most recent entry
            latest_entry = max(self._global_storage.values(), key=lambda x: x['timestamp'])
            return latest_entry['usage_data']
    
    def clear_usage(self) -> None:
        """Clear token usage data for the current thread/request."""
        if hasattr(self._local, 'usage_data'):
            delattr(self._local, 'usage_data')
    
    def has_usage(self) -> bool:
        """Check if token usage data is available."""
        return hasattr(self._local, 'usage_data') and self._local.usage_data is not None


# Global instance for tracking token usage
token_usage_tracker = TokenUsageTracker()