"""
Helper utilities for safe Celery task execution with fallback to synchronous execution.
"""
import logging
from functools import wraps

logger = logging.getLogger(__name__)


def safe_async_task(task_func):
    """
    Decorator to safely execute Celery tasks with automatic fallback to synchronous execution.
    
    If the task's .delay() method fails (e.g., due to missing Redis), the task will be 
    executed synchronously in the current process.
    """
    @wraps(task_func)
    def wrapper(*args, **kwargs):
        try:
            # Try to execute asynchronously
            return task_func.delay(*args, **kwargs)
        except Exception as e:
            logger.warning(
                f"Failed to execute task '{task_func.name}' asynchronously: {type(e).__name__}: {str(e)}. "
                f"Falling back to synchronous execution."
            )
            try:
                # Fall back to synchronous execution
                return task_func.apply(*args, **kwargs)
            except Exception as sync_error:
                logger.error(
                    f"Synchronous execution of task '{task_func.name}' also failed: "
                    f"{type(sync_error).__name__}: {str(sync_error)}"
                )
                raise
    
    return wrapper


def call_task_safely(task_func, *args, **kwargs):
    """
    Safely call a Celery task with automatic fallback to synchronous execution.
    
    Usage:
        call_task_safely(send_otp_email, user.id, otp.otp_code, otp_type)
    """
    try:
        return task_func.delay(*args, **kwargs)
    except Exception as e:
        logger.warning(
            f"Failed to execute task '{task_func.name}' asynchronously: {type(e).__name__}: {str(e)}. "
            f"Falling back to synchronous execution."
        )
        try:
            return task_func.apply(args, kwargs)
        except Exception as sync_error:
            logger.error(
                f"Synchronous execution of task '{task_func.name}' also failed: "
                f"{type(sync_error).__name__}: {str(sync_error)}"
            )
            raise
