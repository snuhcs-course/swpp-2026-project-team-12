"""Put a built dataset into the app's own DB so the family shows up when the server runs.

Unlike testbed.pipeline, which keeps an isolated test DB and seeds probes only after Graphiti
construction, this seeds every post, comment and past daily question at once. No AI call is made.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..common.django_adapter import TalkDockDjangoAdapter
from ..common.paths import BACKEND_ROOT
from ..common.run_context import PipelineContext, ensure_seedable_manifest


def seed_app(dataset, database=None, media_root=None, backend=BACKEND_ROOT, output=None,
             adapter_class=TalkDockDjangoAdapter):
    context = PipelineContext.create(dataset, output=output, backend=backend)
    manifest = ensure_seedable_manifest(context)
    adapter = adapter_class(
        backend_path=context.backend,
        database=Path(database or context.backend / "db.sqlite3").resolve(),
        media_root=Path(media_root or context.backend / "media").resolve(),
        settings_module=context.settings_module,
    )
    try:
        adapter.setup()
        # The app DB assigns its own room ID; only the isolated test DB pins one for Graphiti.
        result = adapter.seed(manifest, context.manifest, manifest["events"])
        result.update(adapter.seed_conversations(manifest, result["post_ids"]))
    finally:
        adapter.close()
    return result


def main():
    parser = argparse.ArgumentParser(description="데이터셋을 앱 DB에 넣어 서버에서 바로 보이게 합니다.")
    parser.add_argument("--dataset", required=True, help="datasets/ 아래 폴더 이름 또는 config 경로")
    parser.add_argument("--database", help="기본값: backend/db.sqlite3")
    parser.add_argument("--media-root", help="기본값: backend/media")
    parser.add_argument("--backend", default=str(BACKEND_ROOT))
    parser.add_argument("--output", help="build 결과 폴더. 기본값: testbed/output/<dataset_name>")
    args = parser.parse_args()
    result = seed_app(args.dataset, args.database, args.media_root, args.backend, args.output)
    print(f"가족방 {result['family_id']}: 게시물 {len(result['post_ids'])}개, "
          f"댓글 {result['comments']}개, 오늘의 질문 {result['daily_questions']}개")


if __name__ == "__main__":
    main()
