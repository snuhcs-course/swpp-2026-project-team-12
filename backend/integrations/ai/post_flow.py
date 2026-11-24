"""Direct post summary and follow-up QA with bounded evidence retrieval."""
import base64
import json
import logging
from time import perf_counter

from django.conf import settings
from openai import AsyncOpenAI

from apps.families.utils.parent_terms import include_parent_name

from . import prompts
from .options import model_options


def select_budget(results, limit=prompts.FACT_BUDGET, *, episode_limit=None):
    """Select up to limit unique facts and limit unique episodes across all queries."""
    selected = [{'query': r['query'], 'memories': []} for r in results]
    fact_ids = set()
    episode_ids = set()
    episode_limit = limit if episode_limit is None else episode_limit
    for rank in range(max((len(r['memories']) for r in results), default=0)):
        for i, result in enumerate(results):
            if rank < len(result['memories']):
                memory = result['memories'][rank]
                memory_id = memory['id']
                # Standalone episodes cite their own ID. Fact edges cite their source episodes.
                is_episode = memory.get('source_episode_ids') == [memory_id]
                seen, capacity = (episode_ids, episode_limit) if is_episode else (fact_ids, limit)
                if len(seen) < capacity and memory_id not in seen:
                    selected[i]['memories'].append(memory)
                    seen.add(memory_id)
    return selected


def context(memories):
    sources = {s['id']: s for m in memories for s in m.get('sources', [])}
    return {'facts': [{k: v for k, v in m.items() if k != 'sources'} for m in memories],
            'sources': list(sources.values())}


def checked_text(response):
    if response.status != 'completed' or not response.output_text.strip():
        raise RuntimeError('AI 답변이 완료되지 않았습니다.')
    return response.output_text


def tool_queries(calls, parent_terms):
    queries = []
    for call in calls:
        try:
            args = json.loads(call.arguments)
            query = args['query']
            if set(args) != {'query'} or not isinstance(query, str) or not query.strip() or len(query) > 1000:
                raise ValueError()
        except (ValueError, TypeError, KeyError) as error:
            raise RuntimeError('검색 질문 형식이 올바르지 않습니다.') from error
        queries.append(include_parent_name(query, parent_terms, single_query=len(calls) == 1))
    return queries


def tool_outputs(calls, results):
    return [{'type': 'function_call_output', 'call_id': call.call_id,
             'output': json.dumps(context(result['memories']), ensure_ascii=False)}
            for call, result in zip(calls, results, strict=True)]


async def review_query(client, options, text, results):
    """Assess the requested fact against the retrieved records before composing a reply."""
    evidence = [dict(query=r['query'], **context(r['memories'])) for r in results]
    try:
        response = await client.responses.create(
            **{**options, 'instructions': prompts.POST_QA_EVIDENCE_REVIEW},
            input=json.dumps({'요청': json.loads(text), '검색 결과': evidence}, ensure_ascii=False),
            text=prompts.POST_QA_REVIEW_FORMAT, max_output_tokens=160,
        )
        query = json.loads(checked_text(response))['retry_query']
        return query.strip() if isinstance(query, str) and len(query) <= 1000 else ''
    except Exception as error:
        logging.getLogger(__name__).warning('Evidence review failed (%s)', type(error).__name__)
        return ''


async def supplemental_evidence(search, query, queries, results, parent_terms):
    """Look up additional sourced records while retaining the initial evidence."""
    query = include_parent_name(query, parent_terms, single_query=True)
    if query.split() in [earlier.split() for earlier in queries]:
        return []
    queries.append(query)
    try:
        retry, = await search([query])
        seen = {m['id'] for result in results for m in result['memories']}
        new = {'query': query, 'memories': [m for m in retry['memories'] if m['id'] not in seen and m.get('sources')]}
        extra, = select_budget([new], episode_limit=prompts.SUPPLEMENTAL_EPISODE_LIMIT)
        return extra['memories']
    except Exception as error:
        logging.getLogger(__name__).warning('Supplemental evidence search failed (%s)', type(error).__name__)
        return []


async def answer(search, text, feature, *, images=(), timings=None, parent_terms=None, retry_search=None):
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
        queries = tool_queries(calls, parent_terms)
        started = perf_counter()
        results = select_budget(await search(queries))
        timings['search'] = perf_counter() - started
        if len(results) != len(calls):
            raise RuntimeError('검색 결과 개수가 일치하지 않습니다.')
        answer_options = {**options, 'instructions': prompts.POST_QA + '\n' + prompts.POST_QA_FINAL_EVIDENCE}
        extra = []
        if len(queries) < prompts.MAX_QUERIES:
            started = perf_counter()
            query = await review_query(client, options, text, results)
            if query:
                extra = await supplemental_evidence(retry_search or search, query, queries, results, parent_terms)
            timings['search'] += perf_counter() - started
        messages = [*items, *first.output, *tool_outputs(calls, results)]
        if extra:
            messages.append({'role': 'user', 'content': json.dumps({'보완 검색 결과': context(extra)}, ensure_ascii=False)})
        started = perf_counter()
        final = await client.responses.create(**answer_options, input=messages, tools=[prompts.POST_QA_SEARCH_TOOL],
                                             tool_choice='none', max_output_tokens=prompts.ANSWER_MAX_TOKENS)
        timings['answer'] = perf_counter() - started
        memories = [m for r in results for m in r['memories']] + extra
        return {'text': checked_text(final), 'query': queries[0], 'queries': queries, 'memories': memories}
