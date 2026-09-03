# MVP 실행 검증 기록

검증일: 2026-09-04 (Asia/Seoul). Docker Desktop에서 검증했다.

## 빌드와 자동 테스트

- `docker compose up --build -d --wait` 성공. PostgreSQL과 FastAPI의 healthcheck를 통과했고 Next.js 컨테이너의 실행 및 브라우저 접속을 확인했다.
- 잠금 파일로 의존성을 설치한 Next.js 프로덕션 빌드와 TypeScript 검사가 성공했다.
- 별도 Compose 프로젝트 `ragops-validation`의 PostgreSQL에서 단위·통합 테스트 **22개가 모두 통과**했다. 외부 AI API 호출 없이 실행했다.
- Starlette가 사용하는 AnyIO `BlockingPortal` 별칭에 대한 upstream deprecation warning 1개가 있었다.
- `git diff --check`를 통과했다. GitHub Actions 워크플로는 작성했으며 원격 실행 결과는 아직 없다.

## 실제 Gemini와 브라우저 확인

`gemini-3.5-flash-lite`, `gemini-embedding-001` 1536차원, Hybrid, 샘플 문서 12개를 사용했다. API 키는 서버의 `.env`에서 읽었으며 기록에 포함하지 않았다.

| 질문 | 화면 결과 | 관찰 |
| --- | --- | --- |
| OpenAI API 429 오류가 갑자기 증가했어. 재시도는 어떻게 해야 해? | 출처 포함 답변 | 429 Runbook을 S1으로 인용해 지수 백오프·jitter·최대 재시도 제한을 안내했다. 검색 후보 5개, 검색 690ms, 생성 35,551ms, 전체 36,255ms. Trace 접두사 `d343e7b6`. |
| OpenAI API 429 오류 당시 고객사별 실제 피해 금액과 보상 승인자를 알려줘 | 근거 부족 | 관련 후보 5개가 검색됐지만 모델이 `model-refusal`을 반환했다. 답변 출처는 0개, 전체 1,992ms. Trace 접두사 `67fe4845`. |

일반 답변 화면에서 문서 수·provider·모델·토큰·출처가 표시됐고 브라우저 오류 로그는 없었다. 1280px 뷰포트에서 가로 넘침이 없음을 확인했다.

이 결과는 두 요청의 동작 확인이다. 평균 지연시간, 전체 질문의 거절 성능, 답변의 사실 정확도를 보증하는 평가로 해석하지 않는다. 특히 일반 답변은 생성에 약 36초가 걸렸으므로 응답 시간 개선 여지가 있다.

## 후속 검색 평가와 검증

질문 임베딩 재사용 기능 추가 후 전체 테스트 **23개가 통과**했다. 같은 질문 벡터를 공유해도 검색·평가 결과가 같고, 반복 평가에서 임베딩 입력이 중복되지 않는지 PostgreSQL 통합 테스트로 확인했다.

Gemini 의미 임베딩으로 20문항·방식별 1회 비교를 완료했다. [실험 결과와 실패 분석](retrieval-experiment-v2-gemini-budget.md), [원본 JSON](retrieval-experiment-v2-gemini-budget.json)을 참고한다.

전체 생성 답변의 수동 채점은 아직 수행하지 않았다. 각 답변을 Golden Dataset의 `expected_answer_points` 및 인용 문서와 대조하는 것이 다음 과제다.
