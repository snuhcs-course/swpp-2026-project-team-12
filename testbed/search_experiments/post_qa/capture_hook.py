"""Opt-in capture around an already-authorized, sequential app evaluation.

This context manager itself makes no API calls. The wrapped app run still costs money.
Use only in a dedicated single-process experiment, never in a live/shared server.
"""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
from budget_lab import write


@contextmanager
def capture_case(case_id, output_dir):
    from pathlib import Path
    from integrations.ai import post_flow
    original_select = post_flow.select_budget
    original_client = post_flow.AsyncOpenAI
    captured = {'case_id':case_id}

    def select(results, *args, **kwargs):
        captured['results'] = deepcopy(results)
        return original_select(results, *args, **kwargs)

    def client_factory(*args, **kwargs):
        client = original_client(*args, **kwargs)
        create = client.responses.create
        async def wrapped_create(**request):
            if request.get('tool_choice') == 'none':
                # Do not capture the client constructor, API keys, or custom headers.
                allowed={'model','instructions','input','tools','tool_choice','store',
                         'reasoning','service_tier','max_output_tokens'}
                captured['final_request'] = deepcopy({k:v for k,v in request.items() if k in allowed})
                captured['final_request']['input'] = [
                    x.model_dump(mode='json',exclude_none=True) if hasattr(x,'model_dump') else x
                    for x in captured['final_request']['input']]
            return await create(**request)
        client.responses.create = wrapped_create
        return client

    try:
        with patch.object(post_flow,'select_budget',select), patch.object(post_flow,'AsyncOpenAI',client_factory):
            yield captured
    finally:
        # Index by a safe hash, while retaining case_id inside the file.
        from budget_lab import digest
        write(Path(output_dir)/(digest(case_id)+'.json'),captured)
