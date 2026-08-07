---
title: 큰 청크로 인한 검색 품질 저하 분석
document_type: quality-report
service: vector-search
incident_type: RETRIEVAL
severity: P2
version: v2.4.0
---
# 청킹 설정과 검색 품질

## 현상

유사도 점수는 높지만 질문과 직접 관련 없는 긴 문서가 검색됐다. 하나의 청크에 장애 원인, 회고, 조직 공지와 여러 서비스 내용이 함께 포함되어 있었다.

## 분석

청크가 지나치게 크면 관련 키워드가 일부 포함됐다는 이유로 전체 청크가 높은 점수를 받을 수 있다. 반대로 청크가 너무 작으면 원인과 해결 절차가 분리돼 답변에 필요한 문맥이 사라진다.

## 개선

Markdown 제목을 경계로 먼저 분할하고 문장 단위 splitter를 적용한다. 코드 블록과 명령은 가능한 한 같은 청크에 유지한다. 청크 크기와 overlap은 감으로 결정하지 않고 Golden Dataset의 Recall@5, MRR, 출처 정확도로 비교한다. 검색 결과 화면에서 청크 원문과 점수를 확인해 실패 유형을 기록한다.

