# Google AI Studio 무료 등급으로 시작하기

확인일: 2026-09-04. 실제 시연과 의미 검색 실험은 Gemini를 사용했다. [모델 상세](models.md)에서 생성·임베딩 모델의 역할을 확인할 수 있다.

## 1. 키 발급

1. [Google AI Studio API Keys](https://aistudio.google.com/api-keys)에 Google 계정으로 로그인한다.
2. 기본 프로젝트/키가 있으면 사용하거나 `Create API key`로 프로젝트와 키를 만든다.
3. 무료 사용을 원하면 프로젝트의 Billing Tier가 **Free tier**인지 확인한다. 유료 결제를 연결하거나 `Set up billing`으로 업그레이드하지 않는다. 기존 유료 프로젝트의 키는 무료 키와 같지 않다.
4. 키를 복사해 아래 `.env`의 `GEMINI_API_KEY`에 넣는다. 채팅이나 GitHub에 붙여넣지 않는다.

프로젝트 최상위 `.env` 파일에서 다음 항목을 설정한다. `.env.example`은 공유용 예제이므로 실제 키를 넣지 않는다.

```env
AI_PROVIDER=gemini
GEMINI_API_KEY=발급받은_키
GEMINI_CHAT_MODEL=gemini-3.5-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
```

`OPENAI_API_KEY`는 Gemini 모드에서 사용하지 않는다. 키는 백엔드에서만 읽으며 `NEXT_PUBLIC_` 환경변수에 넣지 않는다. `.env`는 Git 추적 대상에서 제외되어 있다.

## 2. 실행

```bash
docker compose up --build -d --wait
```

[웹 화면](http://localhost:3000)에서 `샘플 문서 색인`을 누르고 다음 질문을 입력한다.

> API 429 오류가 늘었어. 재시도는 어떻게 해야 해?

이미지를 다시 빌드할 필요 없이 키/모델 설정만 변경했다면 `docker compose up -d --force-recreate backend`로 환경변수를 다시 읽는다. 단순 `restart`는 변경한 `.env`를 반영하지 않는다.

임베딩 provider 또는 모델을 바꾸면 샘플 문서를 다시 색인한다. 업로드한 문서는 같은 파일을 다시 업로드한다. 모델 변경은 checksum이 같아도 재색인을 수행하며 기존 문서 ID를 유지한다. DB 볼륨을 지울 필요는 없다. 벡터 차원은 현재 기본값 1536을 유지한다.

## 3. 무료 사용 범위와 오류

- 답변 모델 `gemini-3.5-flash-lite`와 임베딩 모델 `gemini-embedding-001`은 확인일 기준 무료 등급이 제공된다. 모델·프로젝트별 요청/토큰/일일 한도가 있으므로 무제한은 아니다.
- 한도는 AI Studio에서 확인한다. 429가 나오면 한도 초기화를 기다린다. 앱은 다른 유료 provider로 자동 전환하지 않는다.
- 무료 등급의 입력·출력은 Google 제품 개선에 사용될 수 있다. 이 프로젝트의 가상 샘플 문서로 시연하고 실제 회사 기밀이나 개인 데이터를 넣지 않는다.
- 화면의 비교 실험은 무료 할당량을 아끼기 위해 1회씩 실행한다. 벡터/Hybrid 평가는 질문 임베딩 API를 호출하므로 반복 실행도 할당량을 소비한다. 소규모 검색 비교에는 `--repetitions 1 --reuse-query-embeddings` 옵션을 사용한다.
- `gemini-2.5-flash-lite`는 이 계정의 실제 호출에서 신규 사용자에게 더 이상 제공되지 않는다는 404를 반환했다. 위 설정은 실제 호출에 성공한 `gemini-3.5-flash-lite`를 사용한다.
- 키 오류/모델 오류는 키를 포함하지 않는 오류 메시지로 표시한다. 키 재발급 전에 프로젝트·모델·할당량을 먼저 확인한다.

## 공식 자료

- [키 발급과 관리](https://ai.google.dev/gemini-api/docs/api-key)
- [무료·유료 모델 가격표](https://ai.google.dev/gemini-api/docs/pricing)
- [프로젝트 결제 등급](https://ai.google.dev/gemini-api/docs/billing)
- [Gemini REST 답변 생성](https://ai.google.dev/api/generate-content)
- [Gemini 임베딩 API](https://ai.google.dev/api/embeddings)
