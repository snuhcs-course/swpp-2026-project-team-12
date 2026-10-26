"""Direct post summary and one-batch, three-way post QA."""
import base64
import json
import logging
from time import perf_counter

from django.conf import settings
from openai import AsyncOpenAI

from . import prompts
from .options import model_options


def select_budget(results, limit=prompts.FACT_BUDGET):
    """Same round-robin, unique-fact budget as the adopted experiment."""
    selected = [{'query': r['query'], 'memories': []} for r in results]
    seen = set()
    for rank in range(max((len(r['memories']) for r in results), default=0)):
        for i, result in enumerate(results):
            if rank < len(result['memories']):
                memory = result['memories'][rank]
                if memory['id'] not in seen:
                    selected[i]['memories'].append(memory)
                    seen.add(memory['id'])
                    if len(seen) == limit:
                        return selected
    return selected


def context(memories):
    sources = {s['id']: s for m in memories for s in m.get('sources', [])}
    return {'facts': [{k: v for k, v in m.items() if k != 'sources'} for m in memories],
            'sources': list(sources.values())}


def checked_text(response):
    if response.status != 'completed' or not response.output_text.strip():
        raise RuntimeError('AI 답변이 완료되지 않았습니다.')
    return response.output_text


async def answer(search, text, feature, *, images=(), timings=None):
    timings = timings if timings is not None else {}
    timings.update(decision=0.0, search=0.0, answer=0.0)
    is_qa = feature == 'post_qa'
    instructions = prompts.POST_QA + '\n' + prompts.POST_QA_RETRIEVAL if is_qa else prompts.POST_SUMMARY
    content = [{'type': 'input_text', 'text': text}]
    for image in images:
        with image.open('rb') as file:
            content.append({'type': 'input_image', 'detail': 'high',
                            'image_url': 'data:image/jpeg;base64,' + base64.b64encode(file.read()).decode()})
    items = [{'role': 'user', 'content': content}]
    options = dict(**model_options('ANSWER' if is_qa else 'SUMMARY'), instructions=instructions, store=False)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
        started = perf_counter()
        if not is_qa:
            response = await client.responses.create(**options, input=items, max_output_tokens=prompts.ANSWER_MAX_TOKENS)
            timings['answer'] = perf_counter() - started
            return {'text': checked_text(response), 'query': None, 'queries': [], 'memories': []}
        first = await client.responses.create(**options, input=items, tools=[prompts.POST_QA_SEARCH_TOOL],
                                             tool_choice='auto', parallel_tool_calls=True,
                                             max_output_tokens=prompts.DECISION_MAX_TOKENS)
        timings['decision'] = perf_counter() - started
        if first.status != 'completed':
            raise RuntimeError('검색 판단이 완료되지 않았습니다.')
        calls = [item for item in first.output if item.type == 'function_call']
        if not calls:
            return {'text': checked_text(first), 'query': None, 'queries': [], 'memories': []}
        # Log only protocol metadata, never private question text or model arguments.
        if len(calls) > prompts.MAX_QUERIES or any(c.name != prompts.POST_QA_SEARCH_TOOL['name'] for c in calls):
            logging.getLogger(__name__).warning('Rejected post QA tools: count=%s names=%s', len(calls), [c.name for c in calls])
            raise RuntimeError('검색 요청 한도를 벗어났습니다.')
        queries = []
        for call in calls:
            try:
                args = json.loads(call.arguments)
                query = args['query']
                if set(args) != {'query'} or not isinstance(query, str) or not query.strip() or len(query) > 1000:
                    raise ValueError()
            except (ValueError, TypeError, KeyError) as error:
                raise RuntimeError('검색 질문 형식이 올바르지 않습니다.') from error
            queries.append(query)
        started = perf_counter()
        results = select_budget(await search(queries))
        timings['search'] = perf_counter() - started
        if len(results) != len(calls):
            raise RuntimeError('검색 결과 개수가 일치하지 않습니다.')
        items.extend(first.output)
        for call, result in zip(calls, results):
            items.append({'type': 'function_call_output', 'call_id': call.call_id,
                          'output': json.dumps(context(result['memories']), ensure_ascii=False)})
        started = perf_counter()
        final = await client.responses.create(**options, input=items, tools=[prompts.POST_QA_SEARCH_TOOL],
                                             tool_choice='none', max_output_tokens=prompts.ANSWER_MAX_TOKENS)
        timings['answer'] = perf_counter() - started
        memories = [m for r in results for m in r['memories']]
        return {'text': checked_text(final), 'query': queries[0], 'queries': queries, 'memories': memories}
