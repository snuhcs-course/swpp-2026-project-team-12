"""One paragraph per author; identity and display labels belong to the server."""

import json


def answer_format(author_ids):
    keys = [str(author_id) for author_id in author_ids]
    return {"format": {
        "type": "json_schema", "name": "daily_digest", "strict": True,
        "schema": {
            "type": "object", "additionalProperties": False,
            "properties": {key: {"type": "string"} for key in keys},
            "required": keys,
        },
    }}


def parse_answer(output, author_ids):
    try:
        paragraphs = json.loads(output)
        if (not isinstance(paragraphs, dict)
                or set(paragraphs) != {str(author_id) for author_id in author_ids}
                or any(not isinstance(text, str) or not text.strip() for text in paragraphs.values())):
            raise ValueError
    except (ValueError, TypeError) as error:
        raise RuntimeError("작성자별 하루 요약을 확인하지 못했습니다.") from error
    return [{"author_id": author_id, "text": " ".join(paragraphs[str(author_id)].split())}
            for author_id in author_ids]
