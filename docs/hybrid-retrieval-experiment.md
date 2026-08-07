# Retrieval 방식 비교 실험

## 목적

벡터 검색만 사용한 기준선과 키워드 검색, Hybrid Retrieval을 동일 조건에서 비교해 검색 품질과 지연시간의 변화를 정량적으로 확인한다. Hybrid를 먼저 채택하고 결과를 정당화하는 것이 아니라, 측정 결과로 현재 데이터셋에 적합한 방식을 선택하는 것이 목적이다.

## 실험 조건

| 항목 | 값 |
| --- | --- |
| 실행일 | 2026-08-07 |
| AI Provider | `local` feature hashing embedding |
| 운영 문서 | 12개 |
| Golden Set | 14개 질문: 답변 가능 12개, 거절 대상 2개 |
| Top-K | 5 |
| Candidate-K | 20 |
| 반복 횟수 | 검색 방식별 5회 |
| Hybrid 가중치 | Vector 0.72, Keyword 0.28 |
| 실행 환경 | Docker Compose 로컬 환경 |

청킹 크기, 문서, 질문, 임베딩, Top-K는 고정하고 검색 방식만 변경했다. 정확도는 결정적이므로 반복마다 동일하며, 검색시간은 5회 실행의 평균을 사용했다.

## 비교 방식

- `Vector Only`: pgvector 코사인 유사도만 사용
- `Keyword Only`: PostgreSQL `ts_rank_cd` 점수만 사용
- `Hybrid`: 정규화한 Vector·Keyword 점수를 `0.72:0.28`로 결합

추천 방식은 `Recall@5`, `MRR`, 거절 정확도 순으로 우선하며 모든 품질 지표가 같으면 평균 검색시간이 짧은 방식을 선택한다.

## 결과

| 검색 방식 | Recall@5 | MRR | 거절 정확도 | 평균 검색시간 |
| --- | ---: | ---: | ---: | ---: |
| Vector Only | 91.7% | 0.819 | 100% | 5.3ms |
| **Keyword Only** | **100%** | **0.917** | **100%** | **4.3ms** |
| Hybrid | **100%** | **0.917** | **100%** | 7.8ms |

### Vector 대비 Hybrid 변화

- Recall@5: `91.7% → 100%`, **8.3%p 개선**
- MRR: `0.819 → 0.917`, **0.097 개선**
- 평균 검색시간: `5.3ms → 7.8ms`, 약 **2.5ms 증가**

Vector Only는 다음 질문에서 정답 문서를 Top-5 안에 포함하지 못했다.

> 문서가 늘어난 뒤 pgvector 쿼리 p95가 느려지고 CPU가 높아졌어

기대 문서는 `pgvector-slow-query.md`였지만 로컬 feature hashing 벡터 검색에서는 관련 없는 임베딩·중복 색인·청킹 문서가 먼저 검색됐다. Keyword와 Hybrid는 `pgvector`, `p95`, `CPU` 용어를 이용해 정답 문서를 검색했다.

## 해석과 결정

현재 로컬 데이터셋의 정량적 우승 방식은 **Keyword Only**다. Hybrid와 검색 품질은 같지만 평균 검색시간이 약 3.5ms 짧기 때문이다. 따라서 이 결과만으로 “Hybrid가 항상 더 좋다”고 주장할 수 없다.

다만 현재 Golden Set은 에러 코드와 기술 용어가 질문에 직접 포함된 비율이 높고, 로컬 feature hashing은 실제 의미 임베딩을 대표하지 않는다. Hybrid의 의미 검색 장점을 검증하려면 다음 실험이 추가로 필요하다.

1. 동일 의미를 다른 표현으로 작성한 패러프레이즈 질문 추가
2. OpenAI Embeddings로 전체 문서 재색인
3. 동일한 비교 API로 5회 반복 측정
4. 품질 향상이 지연시간 증가를 정당화하는지 재판단

서비스는 검색 점수와 두 검색 신호를 시연하기 위해 Hybrid를 기본 파이프라인으로 유지하지만, 포트폴리오 결론은 **“로컬 기준에서는 Keyword가 최적이며 OpenAI 의미 임베딩 실험 전에는 Hybrid 우위를 확정하지 않았다”**로 기록한다.

## 재현 방법

```powershell
docker compose up --build -d
Invoke-RestMethod -Method Post http://localhost:8000/api/documents/seed
Invoke-RestMethod -Method Post "http://localhost:8000/api/evaluations/compare?repetitions=5"
```

요약 원본은 `docs/retrieval-experiment-local.json`에 저장했다.
