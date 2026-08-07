---
title: AI API 인증 401 오류 대응 가이드
document_type: runbook
service: api-gateway
incident_type: API
severity: P2
version: v2
---
# API 인증 401 오류

## 증상

배포 이후 모든 생성 요청이 `401 Unauthorized` 또는 `invalid_api_key`로 실패한다. 일부 Worker만 실패한다면 실행 환경별 Secret 주입 차이를 의심한다.

## 확인 순서

1. API 키 값 자체를 출력하지 않고 환경변수 존재 여부와 마지막 갱신 시각만 확인한다.
2. 로컬, 스테이징, 운영 환경이 서로 다른 Secret 이름을 사용하는지 비교한다.
3. 키 교체 후 오래된 Pod 또는 Worker가 종료되지 않았는지 확인한다.
4. 프론트엔드 번들에 API 키가 포함되지 않았는지 확인한다.

## 대응

Secret Manager의 활성 키를 서버 환경에 다시 주입하고 영향받는 Worker를 순차 재배포한다. 키가 외부에 노출됐을 가능성이 있으면 즉시 폐기하고 새 키를 발급한다. 브라우저에서는 OpenAI API를 직접 호출하지 않고 백엔드 API를 통하도록 한다.

