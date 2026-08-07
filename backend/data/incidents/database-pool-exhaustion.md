---
title: PostgreSQL Connection Pool 고갈 대응
document_type: runbook
service: api-gateway
incident_type: INFRASTRUCTURE
severity: P1
version: v2
---
# Connection Pool 고갈

## 증상

API 요청이 간헐적으로 멈추고 `pool timeout`, `too many connections` 오류가 발생한다. DB CPU는 높지 않지만 애플리케이션의 대기 요청이 증가할 수 있다.

## 원인 후보

- 요청 종료 후 Session을 반환하지 않는다.
- 문서 색인 작업이 긴 트랜잭션을 유지한다.
- Worker와 API 서버의 pool 최대값 합계가 DB 허용 연결 수를 초과한다.
- 외부 API 호출 중 DB 트랜잭션을 열린 상태로 유지한다.

## 대응

요청 단위로 Session을 열고 finally 블록에서 닫는다. 외부 API 호출과 DB 트랜잭션 경계를 분리한다. 서비스별 pool 크기와 DB max connections를 함께 계산한다. 장시간 실행 쿼리와 idle in transaction 세션을 확인한다.

