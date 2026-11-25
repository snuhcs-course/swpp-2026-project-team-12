"""Review pre-fetched family records while writing the Post QA answer."""

import json
import logging
import re
from time import perf_counter

from django.conf import settings
from openai import AsyncOpenAI

from apps.families.utils.parent_terms import include_parent_name
from integrations.ai_workers.temporal_search import DATE_EXPRESSION

from . import post_flow, prompts
from .options import model_options


QUESTION_PARTS = re.compile(r'[,，]| 그리고 | 동시에 ')

EVIDENCE_REVIEW = """
두 번째 입력은 현재 질문을 위해 Graphiti에서 이미 검색한 기록이다. 질문의 항목별로 인물, 사건, 상태, 시점을 대조한다.
현재 글의 원문과 설명에서 확인되는 내용이나 일반 상식에는 다른 기록을 끌어오지 않는다. 게시글 원문과 변경 기록을 우선한다.
현재 상태와 이전 상태, 계획과 실제 완료를 구분한다. 조건이 붙은 기록은 조건과 함께 답한다.
근거를 찾은 부분은 바로 답하고, 확인할 수 없는 부분만 구분해 말한다. 기록이나 사진에 없는 사실을 지어내지 않는다.
"""


def evidence_queries(payload, parent_terms):
    primary = include_parent_name(payload['질문'], parent_terms, single_query=True)
    queries = [primary]
    available = min(256, 999 - len(primary))
    if available > 0:
        caption = DATE_EXPRESSION.sub('', payload.get('원문', '')).strip()
        if caption:
            queries.append(f'{primary}\n{caption[:min(240, available)]}')
    clauses = [clause.strip(' ?') for clause in QUESTION_PARTS.split(primary)]
    if len(clauses) > 1:
        queries.extend(clause for clause in clauses if len(clause) >= 6)
    if '기로' in primary and DATE_EXPRESSION.search(primary):
        # The plan may have been recorded before the day it is meant to occur.
        queries.insert(1, DATE_EXPRESSION.sub('', primary).strip() or primary)
    if available > 0:
        previous = next((turn['text'] for turn in reversed(payload.get('이전대화', [])) if turn['role'] == 'user'), '')
        description = payload.get('게시글 설명', '')
        additional = DATE_EXPRESSION.sub('', f'{previous} {description}').strip()
        if additional:
            queries.append(f'{primary}\n{additional[:available]}')
    return list(dict.fromkeys(queries))[:prompts.MAX_QUERIES]


async def grounded_answer(prefetch, text, timings, parent_terms):
    payload = json.loads(text)
    queries = evidence_queries(payload, parent_terms)
    started = perf_counter()
    try:
        sources = await prefetch(queries)
    except Exception as error:
        logging.getLogger(__name__).warning('Post QA early evidence unavailable (%s)', type(error).__name__)
        return None
    if not sources:
        return None
    timings['search'] = perf_counter() - started

    instructions = prompts.POST_QA + '\n' + prompts.POST_QA_FINAL_EVIDENCE
    evidence = {'게시글': [post_flow.source_context(source) for source in sources]}
    items = [{'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}, {'role': 'user', 'content': json.dumps(
        {'미리 찾은 가족 기록': evidence}, ensure_ascii=False, separators=(',', ':'),
    )}]
    options = dict(**model_options('ANSWER'), store=False)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
        started = perf_counter()
        response = await post_flow.qa_response(
            client, **options, instructions=instructions + '\n' + EVIDENCE_REVIEW,
            input=items, max_output_tokens=prompts.DECISION_MAX_TOKENS,
        )
        timings['answer'] = perf_counter() - started
    memories = [{'id': source['id'], 'fact': source['text'], 'valid_at': None, 'invalid_at': None,
                 'source_episode_ids': [source['id']], 'sources': [source]} for source in sources]
    return {'text': post_flow.checked_text(response), 'query': queries[0], 'queries': queries, 'memories': memories}
