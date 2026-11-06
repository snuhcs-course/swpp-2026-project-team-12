# 가족 추억 찾기 — MemoryQA 실험

- 앱: iteration-3-demo `ed296d4f6c86d4b2b6da48273d5e525e98bd641d`. 앱 소스는 Git archive로 복제하며 수정하지 않는다.
- 기존 MemoryQA 사진 120장 기반 합성 4인 가족의 중첩 100/200/300개 기록. 실제 원본 MemoryQA 정답이 아니라 한국어 합성 사건의 정답이다.
- 이전 2026-11-02 그래프·사진 설명을 동결 재사용. 최신 앱의 검색·답변 경로를 비교하되 최신 construction을 재평가하는 실험은 아니다. Graphiti·Full에 동일한 원본 게시글 설명을 제공한다.
- 30문항: 단일 사실 8, 변경·정정 8, 대상 구분 6, 다중 기록 4, 정보 없음 4. 22개 기존 질문을 조정하고 8개 추가. 원래 30문항과는 다른 평가셋이므로 이전 점수와 직접 비교하지 않는다.
- 질문 시점은 2026-10-17 18:00 KST. 모든 저장 기록은 이전 시점이며 현재 평가 게시글/사진은 제외. 작성자/시각은 출처에 포함. 질문자의 가족 호칭에 의존하지 않는다.
- Luna Fast, reasoning none, 출력 1,200토큰, 앱 HISTORY_INSTRUCTIONS와 출처 JSON schema 공통. Graphiti는 실제 family_history 2-way, Full은 모든 게시글 sources와 가족 등록 기록을 같은 schema에 제공한다.
- 예비: 100개 규모의 유형별 10문항 × 2방식 × 1회 = 20태스크. 기술적 정상 완료·출처 연결·계측 검증 후 본실험. 정답률이 낮다는 이유로 문항/프롬프트/정답을 수정하지 않는다.
- 본실험: 30문항 × 3규모 × 2방식 × 3회 = 540태스크. 규모별 실행은 순차, 각 규모에서 방식/문항/반복 순서 고정 난수로 섞음. 첫 호출도 포함하며 예비 결과는 본실험에서 제외.

## Metrics

- Answer Accuracy: rubric의 요구 사실 모두 충족. 추가 오류는 별도 기록하고 엄격 정확도도 보고.
- Retrieval Evidence Recall: 정답의 충분 근거 조합 중 최대 게시글 ID recall; 답변 가능한 26문항에서만 계산.
- Citation ID Recall / Precision: 최종 표시 출처 ID를 정답 조합/허용 출처와 비교. 대체 출처로 인한 한계는 Semantic Citation Sufficiency 및 Supported Citation Precision으로 보완.
- Semantic Citation Sufficiency: 표시한 출처만으로 정답 내용을 모두 뒷받침하는지 LLM judge 판정. Supported Citation Precision은 관련 사실을 지지하는 출처 수 / 전체 표시 출처 수(빈 출처 제외).
- Memory Update Error Rate: 변경·정정 8문항에서 이전 상태를 현재로 잘못 답한 비율. 단순 답변 거절은 업데이트 오류로 세지 않지만 정확도는 실패.
- Abstention Accuracy: 정보 없음 4문항에 확인 불가로 답하고 사실을 지어내지 않는 비율. 빈 출처 비율도 별도 보고.
- Online Generation Tokens(input/output/cached), Embedding Tokens, Mean/P95 Latency, Graphiti/Full 비율. 시간은 준비된 데이터를 읽은 뒤 문맥 조립·검색·답변 완료까지; HTTP/worker 큐/UI/TTS와 출처 카드 직렬화는 제외. 출처 연결은 별도 정합성 검증.
- 그래프 적재·사진 설명 재생성은 없음. 채점 비용은 온라인 비교에서 제외하고 별도 집계. API 내부 재시도 비용이 usage에 노출되지 않으면 확인 불가로 명시.

## Grading & checks

같은 Luna Fast judge로 방식/규모를 가리고 의미 판정. 동일 답변·출처는 캐시를 재사용. 질문 시점·가족 관계·원문·정답·실제 표시 출처를 모두 제공한다. 사람의 독립 채점은 아직 없음. 정답·rubric은 실행 전 고정.

입력 파일/앱 소스 hash, 그래프 전체 속성·임베딩 fingerprint, 미래 기록 배제, 세 규모의 정답 근거 불변, SQL 출처 게시글 연결을 검증한다. 공유 앱·그래프는 쓰기 차단. 결과는 추가 기록하며 기존 완료 답변을 재생성하지 않는다. 오류·미실행 수를 분리하고 성능이 낮은 응답도 제외하지 않는다.

합격 기준은 새로 임의 설정하지 않는다. 본 실험은 두 방식의 상대 비교이며 정확도·근거 보존과 토큰·지연의 절충을 보고한다.
