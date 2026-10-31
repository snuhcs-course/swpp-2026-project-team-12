"""An answer selects provenance IDs; it never supplies post IDs or URLs."""

import json


ANSWER_FORMAT = {"format": {
    "type": "json_schema", "name": "family_history_answer", "strict": True,
    "schema": {
        "type": "object", "additionalProperties": False,
        "properties": {
            "text": {"type": "string"},
            "source_episode_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["text", "source_episode_ids"],
    },
}}

INSTRUCTIONS = """
JSON의 text에 사용자에게 보여줄 답변을 작성한다.
source_episode_ids에는 답변의 사실을 뒷받침하는 원문 sources의 id만 관련성이 높은 순서로 넣는다.
검색에 걸렸어도 답변의 근거로 쓰지 않은 기록은 제외한다. id를 만들거나 게시물 번호를 추측하지 않는다.
기록에서 질문의 답을 확인할 수 없으면 모른다고 답하고 source_episode_ids는 빈 목록으로 둔다.
"""


def parse_answer(output, memories):
    try:
        value = json.loads(output)
        if (not isinstance(value, dict) or not isinstance(value.get("text"), str)
                or not value["text"].strip() or not isinstance(value.get("source_episode_ids"), list)
                or any(not isinstance(item, str) for item in value["source_episode_ids"])):
            raise ValueError
    except (ValueError, TypeError) as error:
        raise RuntimeError("추억 답변의 출처를 확인하지 못했습니다.") from error
    allowed = {source["id"] for memory in memories for source in memory.get("sources", [])}
    return {"text": value["text"].strip(), "source_episode_ids": list(dict.fromkeys(
        episode for episode in value["source_episode_ids"] if episode in allowed
    ))}
