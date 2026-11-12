# 배포

| 부분 | 어디 | 비용 | 알아 둘 것 |
| --- | --- | --- | --- |
| 화면 | GitHub Pages (`https://100bee.github.io/lawg/`) | 0원 | `main`에 `frontend/`가 바뀌면 `.github/workflows/pages.yml`이 정적 파일로 내보내 배포 |
| API | Render 무료 웹 서비스 (`render.yaml`) | 0원 | 15분 동안 요청이 없으면 잠들고, 깨우는 데 약 1분. 화면이 열릴 때 `/api/health`를 불러 미리 깨움 |
| DB | Neon 무료 (Postgres + pgvector) | 0원 | 5분 쉬면 잠들고 다음 요청에 깨어남. 월 100 CU-시간 |
| 모델 | Gemini 무료 등급 | 0원 | 입력이 Google 서비스 개선에 쓰일 수 있음(화면 하단에 고지) |

## 처음 한 번

1. **Neon:** 프로젝트를 만들고(리전: AWS Singapore) 연결 문자열을 복사한다. `postgresql://…` 그대로 써도 된다.
2. **Render:** GitHub로 로그인 → New → Blueprint → `100bee/lawg` 선택. 아래 세 값을 입력한다.
   - `GEMINI_API_KEY`: Google AI Studio 키
   - `DATABASE_URL`: Neon 연결 문자열
   - `ADMIN_TOKEN`: 로컬 `.env`의 `DEPLOY_ADMIN_TOKEN` 값
3. **GitHub:** 저장소 변수 `LAWG_API_URL`에 Render 주소(예: `https://lawg-api.onrender.com`)를 넣고 Pages 워크플로를 다시 실행한다.
4. **색인:** 근거 자료를 Gemini로 색인한다.

```bash
curl -X POST "$LAWG_API_URL/api/documents/seed" -H "X-Admin-Token: $DEPLOY_ADMIN_TOKEN"
```

## 공개 배포에서 막아 둔 것

- `ADMIN_TOKEN`이 있으면 색인·업로드·실행 기록·평가 API는 `X-Admin-Token` 헤더가 있어야 한다.
- `/api/report`는 접속한 곳마다 10분에 10건까지 받는다(`REPORT_RATE_LIMIT`, `REPORT_RATE_WINDOW_SECONDS`). 서버 메모리에 세므로 재시작하면 초기화된다.
