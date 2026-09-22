# Email Verification & OTP Redis Connection Fix

## Problem Summary
The application was crashing when attempting to send OTP verification emails because it tried to queue Celery tasks to Redis at `localhost:6379`, which wasn't running.

**Error:** `redis.exceptions.ConnectionError: Error 111 connecting to localhost:6379. Connection refused.`

## Root Cause
1. Celery was not properly configured in the Django project
2. No error handling for Redis connection failures
3. No fallback mechanism for task execution

## Solution Overview
The fix implements a **graceful fallback mechanism** that:
- Executes tasks asynchronously via Celery when Redis is available
- Automatically falls back to synchronous execution if Redis is unavailable
- Logs all failures for debugging
- Works seamlessly without requiring Redis for development

## Implementation Details

### 1. Celery Configuration (`main/celery.py`)
Created a new Celery app with proper Django integration:
```python
from celery import Celery
import os
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'main.settings')
app = Celery('main')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
```

### 2. Django Settings (`main/settings.py`)
Added Celery configuration with sensible defaults:
```python
# Celery Configuration
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'memory://')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'db+sqlite:///celery-results.db')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60  # 30 minutes
CELERY_TASK_ALWAYS_EAGER = os.getenv('CELERY_TASK_ALWAYS_EAGER', 'True').lower() == 'true'
```

**Key Settings:**
- **CELERY_BROKER_URL**: Defaults to in-memory broker (no Redis needed)
- **CELERY_RESULT_BACKEND**: Uses SQLite for results (no Redis needed)
- **CELERY_TASK_ALWAYS_EAGER**: `True` by default (synchronous execution in development)

### 3. Task Utility Module (`auth/task_utils.py`)
Created a helper function that wraps Celery task calls:
```python
def call_task_safely(task_func, *args, **kwargs):
    """
    Safely call a Celery task with automatic fallback to synchronous execution.
    """
    try:
        return task_func.delay(*args, **kwargs)
    except Exception as e:
        logger.warning(
            f"Failed to execute task '{task_func.name}' asynchronously: {type(e).__name__}. "
            f"Falling back to synchronous execution."
        )
        try:
            return task_func.apply(args, kwargs)
        except Exception as sync_error:
            logger.error(f"Synchronous execution of task '{task_func.name}' also failed.")
            raise
```

### 4. Updated Views & Utilities
Replaced all `.delay()` calls with `call_task_safely()`:

**Before:**
```python
send_otp_email.delay(user.id, otp.otp_code, otp_type)
```

**After:**
```python
call_task_safely(send_otp_email, user.id, otp.otp_code, otp_type)
```

Updated files:
- `auth/views.py` (4 updates)
- `auth/tokens.py` (2 updates)

## Behavior

### Development (Default)
- ✅ No Redis required
- ✅ Tasks execute synchronously in the same process
- ✅ Emails sent immediately when endpoint is called
- ✅ Suitable for development and testing

### Production (With Redis)
Configure via environment variables:
```bash
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
CELERY_TASK_ALWAYS_EAGER=False
```

- ✅ Tasks execute asynchronously via Celery
- ✅ Improved performance and scalability
- ✅ HTTP responses return quickly
- ✅ Tasks processed by Celery workers

### Graceful Degradation
If Redis becomes unavailable in production:
- Tasks automatically fall back to synchronous execution
- Application continues to function
- Emails are still sent successfully
- Warning logs track the fallback for debugging

## Testing

### Test 1: Verify Without Redis (Development)
```bash
# Start the development server
./mode/bin/python manage.py runserver

# In another terminal, test the OTP endpoint
curl -X POST http://localhost:8000/api/auth/otp/request/ \
  -H "Content-Type: application/json" \
  -d '{"email": "user@example.com", "otp_type": "EMAIL_VERIFICATION", "send_via": "EMAIL"}'
```

Expected Result:
- ✅ Request succeeds with 200/201 status
- ✅ No Redis errors
- ✅ Email task executes synchronously
- ✅ Response returned immediately with success message

### Test 2: System Check
```bash
./mode/bin/python manage.py check
```

Expected Result:
```
System check identified no issues (0 silenced).
```

### Test 3: Email Verification Flow
1. Register a new user
2. Request OTP via email
3. Verify that email is sent (check logs or email backend)
4. No connection errors should appear

## Configuration Examples

### Development (.env)
```
# Use synchronous execution (no Redis needed)
CELERY_TASK_ALWAYS_EAGER=True
```

### Staging (.env)
```
# Use in-memory broker with eager execution
CELERY_BROKER_URL=memory://
CELERY_RESULT_BACKEND=db+sqlite:///celery-results.db
CELERY_TASK_ALWAYS_EAGER=False  # Can be async when needed
```

### Production (.env)
```
# Use Redis for distributed task queue
CELERY_BROKER_URL=redis://redis.example.com:6379/0
CELERY_RESULT_BACKEND=redis://redis.example.com:6379/0
CELERY_TASK_ALWAYS_EAGER=False
```

## Monitoring & Debugging

### View Task Logs
```bash
# Monitor Celery tasks
tail -f /path/to/celery.log

# Check for fallback warnings
grep "Falling back to synchronous" /path/to/django.log
```

### Django Logs
The application now logs:
1. **WARNING**: When a task fails asynchronously
2. **ERROR**: When both async and sync execution fail
3. Task name, error type, and error message

## Future Enhancements

1. **Celery Beat**: Add scheduled tasks for cleanup
   ```python
   from celery.beat import schedule
   app.conf.beat_schedule = {
       'cleanup-expired-tokens': {
           'task': 'auth.tasks.cleanup_expired_tokens',
           'schedule': schedule(run_every=timedelta(hours=1)),
       },
   }
   ```

2. **Task Retry Logic**: Add exponential backoff
   ```python
   @shared_task(bind=True, autoretry_for=(Exception,), 
                retry_kwargs={'max_retries': 3})
   def send_otp_email(self, user_id, otp_code, otp_type):
       # Implementation
   ```

3. **Task Monitoring**: Use Flower for Celery monitoring
   ```bash
   pip install flower
   flower -A main --port=5555
   ```

## Files Modified

| File | Changes |
|------|---------|
| `main/celery.py` | Created Celery app configuration |
| `main/__init__.py` | Added Celery app import |
| `main/settings.py` | Added Celery configuration section |
| `auth/task_utils.py` | Created safe task execution helper |
| `auth/views.py` | Updated 4 task calls to use `call_task_safely()` |
| `auth/tokens.py` | Updated 2 task calls to use `call_task_safely()` |

## Rollback Plan

If you need to revert to the original behavior:
1. Remove the Celery configuration from settings
2. Revert task calls from `call_task_safely()` to `.delay()`
3. Ensure Redis is running on localhost:6379
4. Remove `main/celery.py` and `auth/task_utils.py`

However, the new implementation is backward compatible and should not cause any issues.

## References

- [Celery Documentation](https://docs.celeryproject.org/)
- [Django Celery Integration](https://docs.celeryproject.org/en/stable/django/)
- [Redis Installation](https://redis.io/docs/getting-started/)
