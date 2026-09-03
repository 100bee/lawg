# Retrieval 방식 비교 실험

현재 검색 비교는 실제 Gemini 의미 임베딩을 사용한 실험을 기준으로 한다.

- [Gemini 실험: 조건·결과·API 사용량·실패 분석](retrieval-experiment-v2-gemini-budget.md)
- [원본 JSON](retrieval-experiment-v2-gemini-budget.json)
- [모델 역할과 설정](models.md)
- [평가 지표 정의](retrieval-experiment-v2.md)

문서 12개·질문 20개에서 Vector·Keyword·Hybrid를 같은 조건으로 비교했다. Gemini Vector는 Recall@5 100%, MRR 1.000이었지만 검색 근거 판정은 거절 대상 5개를 모두 허용했다. 검색 성능과 답변 가능성 판정을 구분해 해석한다.
