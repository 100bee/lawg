---
title: pgvector 검색 지연 대응 Runbook
document_type: runbook
service: vector-search
incident_type: INFRASTRUCTURE
severity: P2
version: v2
---
# pgvector 검색 지연

## 증상

Vector Search의 p95 지연시간이 증가하고 PostgreSQL CPU 사용률이 높아진다. 문서 수가 증가할수록 전체 테이블을 순차 탐색하는 쿼리가 느려진다.

## 확인

1. `EXPLAIN ANALYZE`로 벡터 인덱스 사용 여부를 확인한다.
2. embedding 차원과 컬럼 타입이 쿼리 벡터와 같은지 확인한다.
3. 서비스 또는 고객 필터가 검색 전에 적용되는지 확인한다.
4. autovacuum과 통계 정보가 최신인지 확인한다.

## 대응

데이터 규모와 쓰기 패턴에 맞는 HNSW 또는 IVFFlat 인덱스를 검토한다. 후보 검색 수와 Top-K를 무작정 크게 설정하지 않는다. 필터 컬럼에 일반 인덱스를 추가하고 검색 지연시간을 벡터 검색과 답변 생성으로 분리해 측정한다.

