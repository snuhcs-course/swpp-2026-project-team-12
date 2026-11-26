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
질문의 각 항목에 필요한 인물·행동·상태를 확인하고, 요청한 사실과 그 사실에 필요한 조건만 답한다.
게시시각과 recorded_at은 글을 올린 시각이다. 원문의 '오늘', '이번 주'는 그 글의 게시시각을 기준으로 해석하고, 질문의 날짜 표현은 현재시각을 기준으로 해석한다.
해당 날짜에 적용되는 기록을 사용한다. 최신 담당이나 상태에 조건이 붙으면 그 조건을 밝히고, 실제로 조건이 충족됐는지는 근거가 있을 때만 말한다.
가족 사실은 같은 대상의 원문과 변경 기록을 대조해 확인한다. 답변에 필요 없는 날짜, 이름, 과거 경위는 생략한다.
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

    evidence = {'게시글': [post_flow.source_context(source) for source in sources]}
    items = [{'role': 'user', 'content': [{'type': 'input_text', 'text': text}]}, {'role': 'user', 'content': json.dumps(
        {'미리 찾은 가족 기록': evidence}, ensure_ascii=False, separators=(',', ':'),
    )}]
    options = dict(**model_options('ANSWER'), store=False)
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
        started = perf_counter()
        response = await post_flow.qa_response(
            client, **options, instructions=prompts.POST_QA + EVIDENCE_REVIEW,
            input=items, max_output_tokens=prompts.DECISION_MAX_TOKENS,
        )
        timings['answer'] = perf_counter() - started
    memories = [{'id': source['id'], 'fact': source['text'], 'valid_at': None, 'invalid_at': None,
                 'source_episode_ids': [source['id']], 'sources': [source]} for source in sources]
    return {'text': post_flow.checked_text(response), 'query': queries[0], 'queries': queries, 'memories': memories}
