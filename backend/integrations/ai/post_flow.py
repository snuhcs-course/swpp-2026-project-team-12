"""Direct post summary and follow-up QA with bounded evidence retrieval."""
import base64
import json
import logging
from time import perf_counter

from django.conf import settings
from openai import AsyncOpenAI

from apps.families.utils.parent_terms import include_parent_name

from . import prompts
from .options import model_options, llm_response
from integrations.telemetry import measured


def select_budget(results, fact_limit=prompts.FACT_BUDGET, episode_limit=prompts.EPISODE_BUDGET):
    """Round-robin across queries with separate unique fact and episode budgets.

    Episodes get their own budget so update posts that Graphiti did not turn into
    facts are not crowded out by older facts that rank first.
    """
    selected = [{'query': r['query'], 'memories': []} for r in results]
    limits = {'fact': fact_limit, 'episode': episode_limit}
    seen = {'fact': set(), 'episode': set()}
    for rank in range(max((len(r['memories']) for r in results), default=0)):
        for i, result in enumerate(results):
            if rank < len(result['memories']):
                memory = result['memories'][rank]
                # Standalone episodes cite their own ID.
                kind = 'episode' if memory.get('source_episode_ids') == [memory['id']] else 'fact'
                if memory['id'] not in seen[kind] and len(seen[kind]) < limits[kind]:
                    selected[i]['memories'].append(memory)
                    seen[kind].add(memory['id'])
    return selected


def source_context(source):
    if "post_fields" not in source:
        return source
    return {"id": source["id"], "name": source["name"], "recorded_at": source["recorded_at"], **source["post_fields"]}


def context(memories):
    sources = {s['id']: s for m in memories for s in m.get('sources', [])}
    return {
        'facts': [{k: v for k, v in m.items() if k != 'sources'} for m in memories
                  if not (m.get('source_episode_ids') == [m['id']] and "post_fields" in sources.get(m['id'], {}))],
        'sources': [source_context(source) for source in sources.values()],
    }


def checked_text(response):
    if response.status != 'completed' or not response.output_text.strip():
        raise RuntimeError('AI 답변이 완료되지 않았습니다.')
    return response.output_text


@measured("llm_stream")
async def qa_response(client, **options):
    stream = await llm_response(client, **options, stream=True)
    response = None
    async with stream:
        # Drain the end of the stream so the SDK can reuse the connection.
        async for event in stream:
            if event.type in {'response.completed', 'response.incomplete', 'response.failed'}:
                response = event.response
            if event.type == 'error':
                raise RuntimeError('AI 응답 스트림이 완료되지 않았습니다.')
    if response is not None:
        return response
    raise RuntimeError('AI 응답 스트림이 완료되지 않았습니다.')


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
        response = await qa_response(
            client,
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


def image_input(photo):
    with photo.open('rb') as file:
        image_url = 'data:image/jpeg;base64,' + base64.b64encode(file.read()).decode()
    return {'type': 'input_image', 'detail': 'high', 'image_url': image_url}


async def answer(search, text, feature, *, images=(), timings=None, parent_terms=None, retry_search=None, prefetch=None):
    timings = timings if timings is not None else {}
    timings.update(decision=0.0, search=0.0, answer=0.0)
    is_qa = feature == 'post_qa'
    if is_qa and prefetch is not None:
        from .post_grounding import grounded_answer

        grounded = await grounded_answer(prefetch, text, timings, parent_terms)
        if grounded is not None:
            return grounded
    instructions = prompts.POST_QA + '\n' + prompts.POST_QA_RETRIEVAL if is_qa else prompts.POST_SUMMARY
    content = [{'type': 'input_text', 'text': text}]
    tools = [prompts.POST_QA_SEARCH_TOOL]
    if not is_qa:
        content.extend(image_input(image) for image in images)
    items = [{'role': 'user', 'content': content}]
    options = dict(**model_options('ANSWER' if is_qa else 'SUMMARY'), instructions=instructions, store=False)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
        started = perf_counter()
        if not is_qa:
            response = await llm_response(client, **options, input=items, max_output_tokens=prompts.ANSWER_MAX_TOKENS)
            timings['answer'] = perf_counter() - started
            return {'text': checked_text(response), 'query': None, 'queries': [], 'memories': []}
        first = await qa_response(client, **options, input=items, tools=tools, tool_choice='auto',
                                  parallel_tool_calls=True, max_output_tokens=prompts.DECISION_MAX_TOKENS)
        timings['decision'] = perf_counter() - started
        if first.status != 'completed':
            raise RuntimeError('검색 판단이 완료되지 않았습니다.')
        calls = [item for item in first.output if item.type == 'function_call']
        if not calls:
            return {'text': checked_text(first), 'query': None, 'queries': [], 'memories': []}
        # Log only protocol metadata, never private question text or model arguments.
        if len(calls) > prompts.MAX_QUERIES or any(call.name != prompts.POST_QA_SEARCH_TOOL['name'] for call in calls):
            logging.getLogger(__name__).warning('Rejected post QA tools: count=%s names=%s', len(calls), [c.name for c in calls])
            raise RuntimeError('검색 요청 한도를 벗어났습니다.')
        queries = tool_queries(calls, parent_terms)
        started = perf_counter()
        results = select_budget(await search(queries))
        if len(results) != len(calls):
            raise RuntimeError('검색 결과 개수가 일치하지 않습니다.')
        extra = []
        if len(queries) < prompts.MAX_QUERIES:
            query = await review_query(client, options, text, results)
            if query:
                extra = await supplemental_evidence(retry_search or search, query, queries, results, parent_terms)
        timings['search'] = perf_counter() - started
        answer_options = {**options, 'instructions': prompts.POST_QA + '\n' + prompts.POST_QA_FINAL_EVIDENCE}
        messages = [*items, *first.output, *tool_outputs(calls, results)]
        if extra:
            messages.append({'role': 'user', 'content': json.dumps({'보완 검색 결과': context(extra)}, ensure_ascii=False)})
        started = perf_counter()
        final = await qa_response(client, **answer_options, input=messages, tools=tools, tool_choice='none',
                                  max_output_tokens=prompts.ANSWER_MAX_TOKENS)
        timings['answer'] = perf_counter() - started
        memories = [m for r in results for m in r['memories']] + extra
        return {'text': checked_text(final), 'query': queries[0] if queries else None, 'queries': queries, 'memories': memories}
