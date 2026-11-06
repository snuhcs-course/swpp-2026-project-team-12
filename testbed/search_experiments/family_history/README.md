# Family History Search

[평가 문항·정답·근거](cases.json), [공통 검증과 채점 주의사항](../README.md).

공통 30문항, 100/200/300개 기록, Full History/Graphiti, 3회 반복이다. 답변 모델은 Luna Fast/none/1,200토큰. 질문에는 현재 게시글이나 사진을 넣지 않는다. Full도 과거 사진 대신 Graphiti와 같은 동결 설명을 받는다.

## 준비와 읽기 전용 검사

상위 README대로 `family_history-inputs.tar.gz`를 가져오면 `.inputs/`와 고정 앱 `.runtime/backend`가 준비된다. 앱 커밋이 로컬 Git에 없으면 먼저 해당 커밋을 fetch한다. 현재 checkout의 backend는 실행하지 않는다.

별도의 **빈 Neo4j 5.26**를 준비하고 `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` 환경변수를 설정한다. 서비스 DB 주소를 사용하지 않는다. 아래 복원은 빈 DB만 허용하고 원래 임베딩을 그대로 복원하며 LLM을 호출하지 않는다.

```sh
python testbed/search_experiments/family_history/restore_graph.py --allow-db-write
python testbed/search_experiments/family_history/test_contract.py
python testbed/search_experiments/family_history/run.py check --size 100
python testbed/search_experiments/family_history/run.py check --size 200
python testbed/search_experiments/family_history/run.py check --size 300
```

`check`는 임베딩을 로컬 고정값으로 대체해 실제 검색·출처 연결을 검사한다. 검색 정확도를 측정하는 호출은 아니다. 실행 중 SQL과 그래프는 읽기 전용으로 제한하고 그래프 fingerprint를 비교한다.

## 유료 재실행 — 명시적으로 선택

`OPENAI_API_KEY`를 환경변수로 설정한 뒤 사용한다. 키 파일은 자동으로 찾지 않는다. 과거 측정 결과는 `recorded.json.xz`에 있고, 아래 실행은 별도 `output/`에 새 답변을 만든다.

```sh
python testbed/search_experiments/family_history/run.py full --size 100 --allow-paid
python testbed/search_experiments/family_history/run.py full --size 200 --allow-paid
python testbed/search_experiments/family_history/run.py full --size 300 --allow-paid
python testbed/search_experiments/family_history/grade.py full --allow-paid
python testbed/search_experiments/family_history/audit.py full --complete
python testbed/search_experiments/family_history/report.py full
```

540개 답변 외 검색 임베딩·채점에도 비용이 든다. 완료 ID는 건너뛰며, 오류가 기록되면 내용을 검토한 뒤 재개한다. 유료 호출을 재현해도 비결정성·서버 상태로 정답과 시간은 달라질 수 있다. `recorded.json.xz`의 원래 결과와 `output/`의 새 결과를 섞지 않는다.

세 그래프는 각각 구축돼 fact가 완전히 중첩되지 않는다. 규모 효과와 추출 차이를 분리한 실험이 아니다. 사진 이해·새 construction·HTTP·작업 큐·TTS는 평가하지 않는다.
