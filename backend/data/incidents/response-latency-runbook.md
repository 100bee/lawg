---
title: RAG 응답 지연 분석 Runbook
document_type: runbook
service: answer-service
incident_type: PERFORMANCE
severity: P2
version: v2
---
# RAG 응답 지연 분석

## 측정 원칙

전체 응답시간만 보면 병목을 찾기 어렵다. 문서 검색, reranking, 프롬프트 구성, 모델 응답 시작, 전체 생성 시간을 구분해 기록한다.

## 확인 순서

1. retrieval latency와 generation latency를 비교한다.
2. 검색 후보 수와 최종 컨텍스트 크기를 확인한다.
3. 모델 또는 reasoning 설정이 변경됐는지 확인한다.
4. DB connection pool 대기시간과 외부 API 재시도를 확인한다.

## 대응

검색이 병목이면 인덱스와 필터 순서를 점검한다. 생성이 병목이면 불필요한 컨텍스트를 줄이고 스트리밍을 적용한다. timeout을 늘리는 것은 원인 분석 이후 임시 완화책으로만 사용한다. 평균뿐 아니라 p95와 p99를 함께 관찰한다.

