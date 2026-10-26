"""Shared LLM flow: answer, search → answer, or decide → search → answer."""

import base64
import json
from time import perf_counter

from django.conf import settings
from django.utils import timezone
from openai import AsyncOpenAI

from . import prompts
from .options import model_options
from .provider import FEATURE_INSTRUCTIONS

def memory_context(memories):
    """Send each source once, even when it supports multiple facts."""
    sources = {source["id"]: source for memory in memories for source in memory.get("sources", [])}
    return {"facts": [{key: value for key, value in memory.items() if key != "sources"}
                      for memory in memories], "sources": list(sources.values())}

def two_way_or_three_way(feature):
    if feature in {"post_summary", "digest"}:
        return 1
    if feature == "family_history":
        return 2
    if feature in FEATURE_INSTRUCTIONS:
        return 3
    raise ValueError("지원하지 않는 AI 기능이에요.")


# Model group that writes each feature's final answer; the search decision uses QUERY.
ANSWER_GROUPS = {"digest": "SUMMARY", "stt_correction": "STT", "family_history": "ANSWER"}


def choose_instruction(feature):
    if feature in {"post_summary", "post_qa"}:
        return prompts.POST_SUMMARY if feature == "post_summary" else prompts.POST_QA + "\n" + prompts.POST_QA_RETRIEVAL
    ways = two_way_or_three_way(feature)
    if ways == 1:
        return FEATURE_INSTRUCTIONS[feature]
    if ways == 2:
        return prompts.HISTORY_INSTRUCTIONS
    return FEATURE_INSTRUCTIONS[feature] + prompts.RETRIEVAL_INSTRUCTIONS


async def answer_with_memory(search, text, feature, *, images=(), timings=None):
    """The search callback is bound to a family by the server, not the model."""
    if feature in {"post_summary", "post_qa"}:
        from .post_flow import answer
        return await answer(search, text, feature, images=images, timings=timings)
    instructions = choose_instruction(feature)
    query_options, answer_options = model_options("QUERY"), model_options(ANSWER_GROUPS[feature])
    ways = two_way_or_three_way(feature)
    two_way = ways == 2
    timings = timings if timings is not None else {}
    timings.update(decision=0.0, search=0.0, answer=0.0)
    queries, results = [text], []
    content = [{"type": "input_text", "text": text}]
    for image in images:
        with image.open("rb") as file:
            content.append({
                "type": "input_image", "detail": "low",
                "image_url": "data:image/jpeg;base64," + base64.b64encode(file.read()).decode(),
            })
    items = [{"role": "user", "content": content}]

    # Single search for two-way flow
    if two_way:
        started = perf_counter()
        results = await search(queries)
        timings["search"] = perf_counter() - started
        if not results[0]["memories"]:
            return {"text": "가족 기록에서 관련 내용을 찾지 못했어요.", "query": text, "memories": []}

    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60, max_retries=1) as client:
        if ways == 3:
            # Decide whether to search or answer directly, and make up to three search queries.
            started = perf_counter()
            first = await client.responses.create(
                **query_options, instructions=instructions, input=items,
                tools=[prompts.SEARCH_TOOL], tool_choice="auto", parallel_tool_calls=True,
                max_output_tokens=700, store=False,
            )
            timings["decision"] = perf_counter() - started
            if first.status != "completed":
                raise RuntimeError("검색 판단 응답이 완료되지 않았습니다.")
            calls = [item for item in first.output if item.type == "function_call"]
            if not calls:
                if not first.output_text.strip():
                    raise RuntimeError("최종 답변이 완료되지 않았습니다.")
                return {"text": first.output_text, "query": None, "memories": []}
            if len(calls) > 3 or any(call.name != prompts.SEARCH_TOOL["name"] for call in calls):
                raise RuntimeError("검색 요청을 처리하지 못했습니다.")
            
            # Multiple searches for three-way flow
            queries = [json.loads(call.arguments)["query"] for call in calls]
            started = perf_counter()
            results = await search(queries)
            timings["search"] = perf_counter() - started
            # Preserve reasoning only for the same model, and return an output for every tool call.
            same_model = query_options["model"] == answer_options["model"]
            items.extend(item for item in first.output if same_model or item.type != "reasoning")
            items.extend({
                "type": "function_call_output", "call_id": call.call_id,
                "output": json.dumps(memory_context(result["memories"]), ensure_ascii=False),
            } for call, result in zip(calls, results))

        memories = {memory["id"]: memory for result in results for memory in result["memories"]}
        # Only the three-way flow keeps the tool definition for its tool-call history.
        options = {"tools": [prompts.SEARCH_TOOL], "tool_choice": "none"} if ways == 3 else {}
        if two_way:
            items = json.dumps({
                "질문": text, "현재 시각": timezone.now().isoformat(),
                "기록": memory_context(list(memories.values())),
            }, ensure_ascii=False)
        started = perf_counter()
        final = await client.responses.create(
            **answer_options, instructions=instructions, input=items,
            max_output_tokens=700, store=False, **options,
        )
        timings["answer"] = perf_counter() - started
        if final.status != "completed" or not final.output_text.strip():
            raise RuntimeError("최종 답변이 완료되지 않았습니다.")
        result = {"text": final.output_text, "query": queries[0] if ways > 1 else None,
                  "memories": list(memories.values())}
        if ways == 3:
            result["queries"] = queries
        return result
