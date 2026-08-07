---
title: 문서 중복 색인 대응 Runbook
document_type: runbook
service: ingestion-worker
incident_type: INGESTION
severity: P3
version: v2
---
# 문서 중복 색인 대응

## 증상

동일한 문서와 문장이 검색 결과에 여러 번 나타나고 답변 출처가 중복 표시된다. 재업로드 이후 청크 수가 계속 증가하는 현상이 동반될 수 있다.

## 원인 후보

- 파일 내용 checksum을 검사하지 않고 매번 새 Document를 생성했다.
- 문서 갱신 시 이전 청크 삭제와 새 청크 삽입이 하나의 트랜잭션으로 처리되지 않았다.
- 동일 업로드 요청이 네트워크 재시도로 두 번 처리됐다.

## 대응

원문 전체의 SHA-256 checksum과 source name을 함께 비교한다. 내용이 같으면 색인을 건너뛰고, 내용이 변경되면 이전 청크를 삭제한 뒤 새 버전을 저장한다. 업로드 요청에는 idempotency key를 부여한다. 중복 제거 후 영향을 받은 문서만 재색인한다.

