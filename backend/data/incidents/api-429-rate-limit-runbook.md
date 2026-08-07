---
title: OpenAI API 429 오류 대응 Runbook
document_type: runbook
service: api-gateway
incident_type: API
severity: P2
version: v2
---
# OpenAI API 429 오류 대응

## 증상

Answer Service 호출에서 `429 Too Many Requests`가 증가하고 일부 사용자 요청이 재시도 후에도 실패한다. 애플리케이션 로그에는 `rate_limit_exceeded`, `requests per minute`, `tokens per minute` 중 하나가 기록될 수 있다.

## 즉시 확인

1. 오류 응답의 request ID와 발생 시각을 확보한다.
2. 같은 시각의 요청 수와 입력 토큰 합계를 확인한다.
3. 배포 직후 동시 요청 수, 재시도 횟수, 최대 출력 토큰 설정이 변경됐는지 확인한다.
4. 클라이언트가 429 응답을 즉시 반복 호출하고 있지 않은지 확인한다.

## 대응

재시도는 지수 백오프와 jitter를 적용하고 최대 횟수를 제한한다. 긴 문서를 한 요청에 몰아넣는 경우 청크 수와 컨텍스트 예산을 줄인다. 실시간 처리가 필요하지 않은 색인 작업은 사용자 질문 처리와 분리한다. 동일 질문의 중복 요청은 idempotency key 또는 짧은 캐시로 합친다.

## 금지 사항

429가 발생했다는 이유만으로 무제한 재시도를 활성화하지 않는다. API 키를 로그나 장애 티켓에 남기지 않는다.

