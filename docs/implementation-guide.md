# 여덟 단계 구현 가이드

목표는 가상의 B2B RAG 운영팀을 위한 **검색·평가 중심 MVP**다. API 오류, 색인 실패, 검색 품질, 응답 지연과 토큰 증가를 다룬다. 인증·조직 권한·자동 복구는 이 MVP의 범위 밖이다.

## 1. 범위와 데이터 정의

- 운영 문서: `backend/data/incidents/`의 Runbook·장애 회고·정책 12개.
- Golden Dataset: `backend/data/evaluations.jsonl`의 20개 질문.
- 기존 질문 14개는 `dev`, 추가 질문 6개는 `challenge`다. 표현을 바꾼 질문, 관련 단어는 있지만 답은 없는 질문, 복수 문서 질문을 포함한다.
- 각 행은 `id`, `split`, `category`, `question`, `expected_documents`, `answerable`, `expected_answer_points`를 가진다. `expected_answer_points`는 사람이 생성 답변을 검토할 때 쓰며 자동 검색 점수에는 반영하지 않는다.
- 완료 확인: 질문별 정답 문서와 답변 거절 여부를 사람이 설명할 수 있다.

## 2. 인프라 뼈대

```bash
# 저장소 최상위에서 실행. 기존 설정을 덮어쓰지 않는다.
test -f .env || cp .env.example .env
# .env에 AI_PROVIDER=gemini와 Gemini 키·모델을 설정한 뒤 실행
docker compose up --build -d --wait
```

DB의 healthcheck 통과 후 백엔드를 시작하고, 백엔드의 healthcheck 통과 후 프론트엔드를 시작한다. 주소는 `http://localhost:3000`, API 문서는 `http://localhost:8000/docs`다. 서비스 포트는 기본적으로 로컬 컴퓨터에만 노출된다. 포트 충돌은 `DB_PORT`, `BACKEND_PORT`, `FRONTEND_PORT`로 조정할 수 있다.

실제 모델과 키 설정은 [Gemini 설정](gemini-setup.md)을 따른다.

## 3. 색인 파이프라인

`routes.upload_document` → `ingestion.ingest_markdown_text` → `chunking.split_document` → `ai.embed_texts` → PostgreSQL.

- UTF-8 Markdown/TXT, 최대 2MB. 빈 본문과 닫히지 않은 frontmatter는 400으로 처리한다.
- **문서 본문·메타데이터·파일명 마스킹 후** checksum, 청킹, 임베딩, DB 저장을 수행한다.
- checksum이 같으면 다른 파일명이어도 중복 색인하지 않는다. 기존 문서를 갱신할 때는 문서 ID를 유지한다.
- 청크에 임베딩 provider·모델·차원과 마스킹 버전을 저장한다. 설정이 바뀌면 동일 파일도 재색인한다.
- 완료 확인: 같은 파일을 두 번 넣어도 청크가 증가하지 않고, 모델 변경 후 재색인할 수 있다.

## 4. 독립적인 검색 방식

`services/retrieval.py`는 Vector, Keyword, Hybrid를 각각 지원한다. 화면과 `/api/chat`의 `retrieval_mode`로 선택한다.

Hybrid 순위는 벡터 유사도와 정규화한 키워드 순위 점수를 0.72:0.28로 결합한다. 이 비율은 초기 실험값이며 최적값으로 보증하지 않는다. 검색 결과가 다른 임베딩 공간과 섞여 있으면 409로 재색인을 요청한다.

## 5. 답변 생성과 근거 제한

- `grounding.evidence_chunks`가 **검색 순위 점수와 별개로** 질문 단어 일치 수·비율과 provider별 벡터 기준을 확인한다. 같은 함수가 채팅과 오프라인 평가에 사용된다.
- Gemini/OpenAI는 `GroundedDraft` 구조로 원인 후보·체크리스트·대응 절차와 출처 ID를 반환한다. 모델 거절, 형식 오류, 없는 출처, 출처 없는 주장은 답변으로 채택하지 않는다.
- `grounded=true`는 이 절차를 통과했다는 뜻이다. 출처 내용이 주장을 실제로 뒷받침하는지는 별도의 평가가 필요하다. UI도 정확도 확률을 표시하지 않는다.
- 새 Trace에는 마스킹한 질문만 저장한다. 기존 버전의 저장 기록은 읽을 때 마스킹하지만 과거 DB 원본을 소급 삭제하지는 않는다. 과거 문서는 다시 색인해야 저장된 본문도 마스킹된다.

## 6. 평가 하네스

```bash
# Gemini로 이미 색인한 환경에서 질문 임베딩을 공유한다.
docker compose exec -T backend python -m app.evaluate --repetitions 1 --reuse-query-embeddings > docs/my-gemini-experiment.json
```

- Recall@K: 검색된 상위 K개 청크의 문서명에서 정답 문서가 얼마나 포함됐는지 질문별 비율의 평균. 정답 문서가 2개인데 하나만 찾으면 0.5.
- MRR: 위 목록의 문서명 중복을 제거한 뒤 첫 정답 문서 순위의 역수 평균.
- Refusal accuracy: 검색 근거 판정의 답변 허용/거절이 Golden Label과 일치한 비율.
- False acceptance: 거절 대상 중 답변을 허용한 비율. False refusal: 답변 가능 질문 중 거절한 비율. 해당 질문이 없으면 null.
- 기본 검색시간은 DB 검색과 질문 임베딩을 포함한다. 위 재사용 옵션에서는 임베딩 준비 시간을 분리한다. 모델 답변 생성 시간은 포함하지 않는다.
- 반복마다 검색 방식 순서를 회전한다. JSON에 dataset/corpus checksum, provider, 임베딩 모델·차원, 청킹, 검색 후보 수, 가중치, 판정 기준, 시간과 개별 실패를 남긴다.

이 평가는 LLM을 호출해 답변의 사실 정확도를 채점하지 않는다. 실제 모델 답변은 `expected_answer_points`와 출처를 대조해 누락·잘못된 조치·근거 없는 주장·거절 여부를 별도 기록한다. 한 번 검토한 challenge는 독립된 최종 시험 세트로 계속 주장하지 말고, 새 질문을 추가한다.

Gemini의 소규모 검색 비교는 `python -m app.evaluate --repetitions 1 --reuse-query-embeddings`로 실행한다. 질문마다 한 번 생성한 벡터를 Vector/Hybrid에 재사용하고 준비 시간을 별도 표시한다. 이 옵션의 검색시간은 DB 검색·정렬만 포함한다. [배치 1회로 실행한 20문항 결과](retrieval-experiment-v2-gemini-budget.md)를 참고한다.

## 7. 관측성 UI

`frontend/app/page.tsx`에서 검색 방식, 출처, 점수, 단어 일치 비율, 후보 수, 검색/생성/전체 지연, 토큰, 모델과 프롬프트 버전을 확인한다. 거절된 경우에도 전체 검색 후보를 펼쳐볼 수 있다. 비교 실험 결과는 JSON으로 내려받는다.

## 8. 검증·기록

[CI 워크플로](../.github/workflows/ci.yml)는 격리된 PostgreSQL DB에서 단위·통합 테스트를 실행한다. 외부 AI API를 호출하지 않는 테스트 환경을 사용한다. `TEST_DATABASE_URL`이 없으면 통합 테스트를 건너뛰므로 테스트용 DB에만 해당 변수를 지정한다. 테스트는 자체 트랜잭션을 롤백한다.

검증한 Python 의존성은 `backend/requirements.lock`, 프론트엔드는 `frontend/package-lock.json`으로 고정한다. 의존성을 변경하면 잠금 파일과 테스트 결과를 함께 갱신한다.

현재 재현 결과는 [Gemini 검색 실험](retrieval-experiment-v2-gemini-budget.md)에 기록한다. 실패한 질문, 판정의 한계, 검색 방식별 차이도 함께 기록한다. 실제 서비스 확장은 인증·조직별 문서 권한, 작업 큐, 문서 버전 정책, 검색 인덱스와 부하 측정 순으로 검토한다.
