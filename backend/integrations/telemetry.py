"""Content-free telemetry. Never pass prompts, HTTP bodies or exception messages here."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import functools
import json
import logging
import os
import re
import threading
import time
import traceback
import uuid

context = ContextVar("telemetry_context", default={})
FIELDS = frozenset("operation_id request_id job_id notification_id component feature stage result attempt duration_ms elapsed_ms method route http_status error_code error_type reason model prompt_version count bytes cache_hit queue_wait_ms".split())


def identifier(value=None):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return str(uuid.uuid4())


def emit(stage, **fields):
    record = {**context.get(), **fields, "stage": stage}
    logging.getLogger("talkdock.telemetry").info("event", extra={"telemetry": record})


class JsonFormatter(logging.Formatter):
    def format(self, record):
        from django.conf import settings
        data = {"schema_version": 1, "event_id": str(uuid.uuid4()),
                "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
                "environment": settings.TELEMETRY_ENVIRONMENT, "server_version": settings.TELEMETRY_VERSION,
                "component": record.name, "service": os.getenv("TELEMETRY_SERVICE", "api"),
                "pid": record.process, "thread": record.threadName, "level": record.levelname}
        source = getattr(record, "telemetry", {})
        data.update({key: value for key, value in source.items() if key in FIELDS and
                     (value is None or isinstance(value, (str, int, float, bool)))})
        # Third-party exceptions can contain family text and credentials. Preserve frames only.
        if record.exc_info:
            data["error_type"] = record.exc_info[0].__name__
            data["stack"] = [{"file": os.path.basename(f.filename), "line": f.lineno, "function": f.name}
                             for f in traceback.extract_tb(record.exc_info[2])]
        if not source:
            data["stage"] = "library_error" if record.levelno >= logging.ERROR else "library_log"
        return json.dumps(data, ensure_ascii=False, allow_nan=False)


@contextmanager
def bind(**fields):
    token = context.set({**context.get(), **fields})
    try:
        yield
    finally:
        context.reset(token)


@contextmanager
def stage(name, **fields):
    start = time.perf_counter()
    result, error_type = "success", None
    try:
        yield
    except BaseException as error:
        result = "timeout" if isinstance(error, TimeoutError) else "error"
        error_type = type(error).__name__
        raise
    finally:
        emit(name, **fields, result=result, error_type=error_type,
             duration_ms=round((time.perf_counter() - start) * 1000, 3))


def measured(name):
    def decorate(fn):
        if __import__("inspect").iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_call(*args, **kwargs):
                with stage(name):
                    return await fn(*args, **kwargs)
            return async_call
        @functools.wraps(fn)
        def call(*args, **kwargs):
            with stage(name):
                return fn(*args, **kwargs)
        return call
    return decorate


class RequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID", "")
        # nginx's $request_id is a 32-digit hex value; UUID also supports direct dev requests.
        request_id = request_id if re.fullmatch(r"[a-fA-F0-9]{32}|[a-fA-F0-9-]{36}", request_id) else identifier()
        operation_id = identifier(request.headers.get("X-Operation-ID"))
        with bind(component="django", operation_id=operation_id, request_id=request_id):
            started = time.perf_counter()
            response = self.get_response(request)
            route = getattr(request.resolver_match, "route", None) or "unmatched"
            status = response.status_code
            emit("http_request", method=request.method, route=route, http_status=status,
                 result="error" if status >= 400 else "success",
                 error_code=f"http_{status}" if status >= 400 else None,
                 duration_ms=round((time.perf_counter() - started) * 1000, 3))
            response["X-Request-ID"] = request_id
            response["X-Operation-ID"] = operation_id
            return response


_runtime_lock = threading.Lock()
_runtime = {}


def runtime(component, **values):
    """Cross-process, content-free gauges; exporter ignores snapshots from dead processes."""
    from django.conf import settings
    from pathlib import Path
    directory = settings.TELEMETRY_STATE_DIR
    if not directory:
        return
    try:
        with _runtime_lock:
            _runtime.setdefault(component, {}).update(values)
            path = Path(directory)
            path.mkdir(parents=True, exist_ok=True)
            destination = path / f"{os.getpid()}.json"
            temporary = path / f"{os.getpid()}.tmp"
            temporary.write_text(json.dumps({"pid": os.getpid(), "updated": time.time(), "components": _runtime}))
            temporary.replace(destination)
    except OSError:
        logging.getLogger(__name__).exception("runtime snapshot failed")
