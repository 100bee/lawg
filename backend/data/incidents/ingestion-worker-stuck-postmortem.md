---
title: 문서 색인 Worker 정체 장애 보고서
document_type: postmortem
service: ingestion-worker
incident_type: INGESTION
severity: P2
version: v2.3.1
---
# 문서 색인 Worker 정체 장애

## 영향

업로드 API는 성공했지만 문서 상태가 `processing`에서 40분 이상 변경되지 않았다. 기존 문서 검색은 정상이고 신규 문서만 검색되지 않았다.

## 원인

배포 과정에서 Worker의 임베딩 요청 timeout이 10초에서 2초로 잘못 변경됐다. timeout 이후 작업은 실패했지만 상태 업데이트 트랜잭션이 rollback되어 `failed`가 아닌 `processing`으로 남았다.

## 진단 방법

- `ingestion_jobs.updated_at`이 오래된 processing 작업을 조회한다.
- API 서버가 아니라 Worker 로그에서 embedding timeout을 확인한다.
- Queue 적체량과 Worker heartbeat를 함께 확인한다.
- 문서 청크가 생성됐지만 임베딩 값이 없는 중간 상태가 있는지 확인한다.

## 해결

임베딩 timeout을 복구하고 멈춘 작업을 `retryable` 상태로 전환했다. 상태 업데이트를 별도 트랜잭션으로 분리하고 오래된 processing 작업을 감지하는 점검을 추가했다.

