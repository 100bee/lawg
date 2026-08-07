"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

type DocumentItem = {
  id: string;
  title: string;
  source_name: string;
  document_type: string;
  service: string;
  incident_type: string;
  severity: string;
  version: string;
  status: string;
};

type Citation = {
  document_id: string;
  title: string;
  source_name: string;
  chunk_index: number;
  heading: string;
  content: string;
  score: number;
  vector_score: number;
  keyword_score: number;
};

type ChatResult = {
  answer: string;
  grounded: boolean;
  confidence: string;
  citations: Citation[];
  trace_id: string;
  diagnostics: {
    masked_question: string;
    inferred_incident_type: string | null;
    retrieval_ms: number;
    generation_ms: number;
    total_ms: number;
    input_tokens: number;
    output_tokens: number;
    provider: string;
    model: string;
    prompt_version: string;
    top_score: number;
  };
};

type RetrievalMode = "vector" | "keyword" | "hybrid";

type EvaluationResult = {
  retrieval_mode: RetrievalMode;
  cases: number;
  recall_at_k: number;
  mrr: number;
  refusal_accuracy: number;
  average_retrieval_ms: number;
};

type RetrievalComparison = {
  dataset: string;
  top_k: number;
  cases: number;
  repetitions: number;
  vector_weight: number;
  keyword_weight: number;
  recommended_mode: RetrievalMode;
  recommendation_policy: string;
  results: EvaluationResult[];
};

const RETRIEVAL_LABELS: Record<RetrievalMode, string> = {
  vector: "Vector Only",
  keyword: "Keyword Only",
  hybrid: "Hybrid",
};

const QUICK_QUESTIONS = [
  "OpenAI API 429 오류가 갑자기 증가했어. 재시도는 어떻게 해야 해?",
  "임베딩 모델을 바꾼 뒤 기존 문서가 검색되지 않아",
  "배포 후 질문당 입력 토큰 비용이 두 배가 됐어",
  "pgvector 검색 p95가 느려지고 CPU가 높아졌어",
];

async function requestApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `요청에 실패했습니다. (${response.status})`);
  }
  return response.json() as Promise<T>;
}

function Metric({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className={`metric ${accent ? "metricAccent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export default function Home() {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [question, setQuestion] = useState(QUICK_QUESTIONS[0]);
  const [chatResult, setChatResult] = useState<ChatResult | null>(null);
  const [comparison, setComparison] = useState<RetrievalComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [seeding, setSeeding] = useState(false);
  const [evaluating, setEvaluating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDocuments = useCallback(async () => {
    try {
      const result = await requestApi<DocumentItem[]>("/api/documents");
      setDocuments(result);
    } catch {
      setDocuments([]);
    }
  }, []);

  useEffect(() => {
    void loadDocuments();
  }, [loadDocuments]);

  const serviceCount = useMemo(
    () => new Set(documents.map((document) => document.service)).size,
    [documents],
  );

  async function seedDocuments() {
    setSeeding(true);
    setError(null);
    try {
      await requestApi("/api/documents/seed", { method: "POST" });
      await loadDocuments();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "색인에 실패했습니다.");
    } finally {
      setSeeding(false);
    }
  }

  async function uploadDocument(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append("file", file);
    setError(null);
    try {
      await requestApi("/api/documents/upload", { method: "POST", body: formData });
      await loadDocuments();
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "업로드에 실패했습니다.");
    } finally {
      event.target.value = "";
    }
  }

  async function askQuestion(event?: FormEvent) {
    event?.preventDefault();
    if (!question.trim()) return;
    setLoading(true);
    setError(null);
    setChatResult(null);
    try {
      const result = await requestApi<ChatResult>("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question.trim() }),
      });
      setChatResult(result);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "질문 처리에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  }

  async function runEvaluation() {
    setEvaluating(true);
    setError(null);
    try {
      const result = await requestApi<RetrievalComparison>("/api/evaluations/compare", { method: "POST" });
      setComparison(result);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : "평가 실행에 실패했습니다.");
    } finally {
      setEvaluating(false);
    }
  }

  return (
    <main className="appShell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brandMark">R</div>
          <div>
            <strong>RAGOps</strong>
            <span>Incident Copilot</span>
          </div>
        </div>

        <div className="environmentCard">
          <div className="statusLine"><span className="statusDot" /> Demo environment</div>
          <strong>AI Service Platform</strong>
          <p>Runbook과 과거 장애를 검색하는 운영 지원 환경</p>
        </div>

        <section className="sideSection">
          <div className="sectionHeading">
            <span>Knowledge base</span>
            <strong>{documents.length}</strong>
          </div>
          <div className="sideStats">
            <span>{serviceCount} services</span>
            <span>Markdown</span>
          </div>
          <button className="secondaryButton fullWidth" onClick={seedDocuments} disabled={seeding}>
            {seeding ? "색인 중..." : "샘플 문서 색인"}
          </button>
          <label className="uploadButton">
            운영 문서 업로드
            <input type="file" accept=".md,.txt" onChange={uploadDocument} />
          </label>
        </section>

        <section className="sideSection documentList">
          <span className="sideLabel">최근 문서</span>
          {documents.slice(0, 6).map((document) => (
            <div className="documentRow" key={document.id}>
              <span className={`severity severity${document.severity}`}>{document.severity}</span>
              <div>
                <strong>{document.title}</strong>
                <span>{document.service}</span>
              </div>
            </div>
          ))}
          {!documents.length && <p className="emptySide">샘플 문서를 먼저 색인해 주세요.</p>}
        </section>

        <div className="sidebarFooter">
          <span>provider</span>
          <strong>{chatResult?.diagnostics.provider ?? "local / openai"}</strong>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <span className="eyebrow">AI SERVICE OPERATIONS</span>
            <h1>장애 대응 Copilot</h1>
          </div>
          <button className="evaluationButton" onClick={runEvaluation} disabled={evaluating}>
            {evaluating ? "비교 실험 중..." : "Retrieval A/B 실험"}
          </button>
        </header>

        <div className="contentGrid">
          <section className="mainColumn">
            <div className="heroCard">
              <div>
                <span className="heroBadge">EVIDENCE-FIRST RAG</span>
                <h2>증상과 로그를 입력하면<br />근거 있는 대응 절차를 찾습니다.</h2>
                <p>운영 문서에 없는 내용은 추측하지 않고 추가로 필요한 정보를 안내합니다.</p>
              </div>
              <div className="heroVisual">
                <span>01</span><i />
                <span>Retrieve</span><i />
                <span>Respond</span>
              </div>
            </div>

            <div className="quickQuestions">
              {QUICK_QUESTIONS.map((quickQuestion, index) => (
                <button key={quickQuestion} onClick={() => setQuestion(quickQuestion)}>
                  <span>0{index + 1}</span>{quickQuestion}
                </button>
              ))}
            </div>

            <form className="questionForm" onSubmit={askQuestion}>
              <div className="formHeader">
                <label htmlFor="incident-question">장애 증상 또는 로그</label>
                <span>API Key와 개인정보는 자동 마스킹</span>
              </div>
              <textarea
                id="incident-question"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                placeholder="예: 배포 후 문서 색인은 완료됐지만 검색 결과에 나오지 않습니다..."
              />
              <div className="formFooter">
                <span>{question.length} / 8000</span>
                <button className="primaryButton" disabled={loading || !question.trim()}>
                  {loading ? "근거 검색 중..." : "장애 분석"}
                </button>
              </div>
            </form>

            {error && <div className="errorBanner">{error}</div>}

            {loading && (
              <div className="loadingCard">
                <div className="loadingPulse" />
                <div><strong>운영 지식 검색 중</strong><span>벡터 검색과 키워드 검색을 결합하고 있습니다.</span></div>
              </div>
            )}

            {chatResult && (
              <article className="answerCard">
                <div className="answerHeader">
                  <div>
                    <span className={`groundingBadge ${chatResult.grounded ? "grounded" : "ungrounded"}`}>
                      {chatResult.grounded ? "근거 확인됨" : "근거 부족"}
                    </span>
                    <span className="confidence">confidence · {chatResult.confidence}</span>
                  </div>
                  <span className="traceId">trace {chatResult.trace_id.slice(0, 8)}</span>
                </div>
                <div className="answerText">{chatResult.answer}</div>
              </article>
            )}
          </section>

          <aside className="debugColumn">
            <section className="debugCard">
              <div className="cardTitle">
                <div><span>RAG TRACE</span><h3>실행 디버그</h3></div>
                <span className="liveBadge">LIVE</span>
              </div>
              {chatResult ? (
                <>
                  <div className="metricGrid">
                    <Metric label="Total" value={`${chatResult.diagnostics.total_ms}ms`} accent />
                    <Metric label="Retrieval" value={`${chatResult.diagnostics.retrieval_ms}ms`} />
                    <Metric label="Generation" value={`${chatResult.diagnostics.generation_ms}ms`} />
                    <Metric label="Top score" value={chatResult.diagnostics.top_score.toFixed(3)} />
                    <Metric label="Input" value={`${chatResult.diagnostics.input_tokens} tok`} />
                    <Metric label="Output" value={`${chatResult.diagnostics.output_tokens} tok`} />
                  </div>
                  <dl className="traceDetails">
                    <div><dt>Incident type</dt><dd>{chatResult.diagnostics.inferred_incident_type ?? "UNKNOWN"}</dd></div>
                    <div><dt>Provider</dt><dd>{chatResult.diagnostics.provider}</dd></div>
                    <div><dt>Model</dt><dd>{chatResult.diagnostics.model}</dd></div>
                    <div><dt>Prompt</dt><dd>{chatResult.diagnostics.prompt_version}</dd></div>
                  </dl>
                </>
              ) : (
                <div className="debugEmpty">
                  <div className="radar"><i /><i /><i /></div>
                  <strong>Trace 대기 중</strong>
                  <span>질문을 실행하면 검색 점수와 지연시간이 표시됩니다.</span>
                </div>
              )}
            </section>

            <section className="sourcesCard">
              <div className="cardTitle">
                <div><span>RETRIEVAL</span><h3>검색 근거</h3></div>
                <strong>{chatResult?.citations.length ?? 0}</strong>
              </div>
              <div className="sourceList">
                {chatResult?.citations.map((citation, index) => (
                  <details className="sourceItem" key={`${citation.document_id}-${citation.chunk_index}`} open={index === 0}>
                    <summary>
                      <span className="sourceIndex">S{index + 1}</span>
                      <div><strong>{citation.title}</strong><span>{citation.heading}</span></div>
                      <em>{citation.score.toFixed(3)}</em>
                    </summary>
                    <div className="scoreBreakdown">
                      <span>vector {citation.vector_score.toFixed(3)}</span>
                      <span>keyword {citation.keyword_score.toFixed(3)}</span>
                    </div>
                    <p>{citation.content}</p>
                  </details>
                ))}
                {!chatResult && <p className="emptySources">답변에 사용된 청크가 여기에 표시됩니다.</p>}
              </div>
            </section>

            {comparison && (
              <section className="evaluationCard">
                <div className="cardTitle">
                  <div><span>RETRIEVAL EXPERIMENT</span><h3>Golden Set 비교</h3></div>
                  <strong>{comparison.cases} × {comparison.repetitions}</strong>
                </div>
                <div className="experimentModes">
                  {comparison.results.map((result) => {
                    const recommended = result.retrieval_mode === comparison.recommended_mode;
                    return (
                      <div className={`experimentMode ${recommended ? "recommendedMode" : ""}`} key={result.retrieval_mode}>
                        <div className="modeHeading">
                          <strong>{RETRIEVAL_LABELS[result.retrieval_mode]}</strong>
                          {recommended && <span>RECOMMENDED</span>}
                        </div>
                        <div className="modeMetrics">
                          <div><span>Recall@{comparison.top_k}</span><strong>{(result.recall_at_k * 100).toFixed(1)}%</strong></div>
                          <div><span>MRR</span><strong>{result.mrr.toFixed(3)}</strong></div>
                          <div><span>Refusal</span><strong>{(result.refusal_accuracy * 100).toFixed(1)}%</strong></div>
                          <div><span>Latency</span><strong>{result.average_retrieval_ms.toFixed(1)}ms</strong></div>
                        </div>
                      </div>
                    );
                  })}
                </div>
                <p className="recommendationNote">
                  선택 기준 · {comparison.recommendation_policy}
                </p>
              </section>
            )}
          </aside>
        </div>
      </section>
    </main>
  );
}
