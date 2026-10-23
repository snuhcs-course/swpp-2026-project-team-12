"""Record SDK usage once, including nested parse/create and Graphiti calls."""
from __future__ import annotations

import contextvars
import time
from collections import defaultdict
from contextlib import contextmanager

CALLS = contextvars.ContextVar("catalog_calls", default=None)
DEPTH = contextvars.ContextVar("catalog_sdk_depth", default=0)
OBSERVER = contextvars.ContextVar("catalog_request_observer", default=None)


@contextmanager
def capture(observer=None):
    calls = []
    token = CALLS.set(calls)
    observer_token = OBSERVER.set(observer)
    try:
        yield calls
    finally:
        CALLS.reset(token)
        OBSERVER.reset(observer_token)


def measured(original, endpoint):
    async def wrapped(self, *args, **kwargs):
        if CALLS.get() is None or DEPTH.get():
            return await original(self, *args, **kwargs)
        token = DEPTH.set(DEPTH.get() + 1)
        started = time.perf_counter()
        row = {"endpoint": endpoint, "requested_model": kwargs.get("model"), "usage": None,
               "requested_service_tier": kwargs.get("service_tier"),
               "requested_reasoning": kwargs.get("reasoning", kwargs.get("reasoning_effort")),
               "output_limit": kwargs.get("max_output_tokens", kwargs.get("max_tokens"))}
        try:
            if OBSERVER.get() is not None:
                OBSERVER.get()(endpoint, kwargs)
            response = await original(self, *args, **kwargs)
            usage = getattr(response, "usage", None)
            row.update(response_id=getattr(response, "id", None), model=getattr(response, "model", kwargs.get("model")),
                       requested_service_tier=kwargs.get("service_tier"), service_tier=getattr(response, "service_tier", None),
                       status=getattr(response, "status", "completed"), usage=usage.model_dump() if usage else None,
                       output_limit=kwargs.get("max_output_tokens", kwargs.get("max_tokens")))
            return response
        except Exception as error:
            row["error_type"] = type(error).__name__
            raise
        finally:
            row["seconds"] = time.perf_counter() - started
            CALLS.get().append(row)
            DEPTH.reset(token)
    return wrapped


@contextmanager
def instrument_sdk():
    from openai.resources.responses.responses import AsyncResponses
    from openai.resources.chat.completions.completions import AsyncCompletions
    from openai.resources.embeddings import AsyncEmbeddings
    originals = []
    for cls, method, endpoint in ((AsyncResponses, "create", "responses"), (AsyncResponses, "parse", "responses_parse"),
                                  (AsyncCompletions, "create", "chat"), (AsyncEmbeddings, "create", "embedding")):
        original = getattr(cls, method)
        originals.append((cls, method, original))
        setattr(cls, method, measured(original, endpoint))
    try:
        yield
    finally:
        for cls, method, original in originals:
            setattr(cls, method, original)


def totals(calls):
    groups = defaultdict(lambda: {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                                 "cached_input_tokens": 0, "reasoning_output_tokens": 0, "usage_complete": True})
    for call in calls:
        row = groups[(call["endpoint"], call.get("model") or call.get("requested_model"))]
        row["calls"] += 1
        usage = call.get("usage")
        if not usage:
            row["usage_complete"] = False
            continue
        row["input_tokens"] += usage.get("input_tokens", usage.get("prompt_tokens", 0))
        row["output_tokens"] += usage.get("output_tokens", usage.get("completion_tokens", 0))
        row["cached_input_tokens"] += (usage.get("input_tokens_details") or usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
        row["reasoning_output_tokens"] += (usage.get("output_tokens_details") or usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
    rows = [{"endpoint": key[0], "model": key[1], **value} for key, value in groups.items()]
    generation = [r for r in rows if r["endpoint"] != "embedding"]
    return {"by_model_endpoint": rows, "usage_complete": bool(calls) and all(r["usage_complete"] for r in rows),
            "observed_generation_tokens": sum(r["input_tokens"] + r["output_tokens"] for r in generation),
            "observed_embedding_tokens": sum(r["input_tokens"] for r in rows if r["endpoint"] == "embedding"),
            "sdk_retry_visibility": "SDK internal retries may consume tokens not exposed by a response; these are not estimated."}
