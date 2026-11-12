"use client";

import { Fragment, FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import type { Category, Cited, RefusalKind, Report, ReportResponse, Role, Source, SourceKind } from "./report";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const CATEGORY: Record<Category, string> = {
  fraud: "온라인 거래 사기",
  insult: "모욕",
  defamation: "명예훼손",
  obscenity: "통신매체이용음란",
  account: "계정 도용·해킹",
  threat: "협박·스토킹",
};
const ROLE: Record<Role, { reading: string; stance: string }> = {
  victim: { reading: "피해를 입은 쪽", stance: "피해를 입은 입장" },
  offender: { reading: "행동을 한 쪽", stance: "행동을 한 입장" },
  third_party: { reading: "주변 사람 (가족·친구 등)", stance: "주변 사람의 입장" },
  unclear: { reading: "아직 모르겠어요", stance: "" },
};
const CHOOSABLE: Role[] = ["victim", "offender", "third_party"];
const KIND: Record<SourceKind, string> = { statute: "조문", precedent: "판례", sentencing: "양형기준", guide: "안내" };
const REFUSAL: Record<RefusalKind, { halt: string; title: string }> = {
  out_of_scope: { halt: "다루는 사건이 아니에요", title: "이 질문에는 답하지 않아요" },
  no_evidence: { halt: "관련 조문을 찾지 못했어요", title: "근거를 찾지 못했어요" },
  individual_conclusion: { halt: "개별 사건의 결론은 답하지 않아요", title: "이 질문에는 답하지 않아요" },
  evasion: { halt: "처벌을 피하는 방법은 안내하지 않아요", title: "이 질문에는 답하지 않아요" },
  referral: { halt: "전문 기관의 도움이 먼저 필요해요", title: "전문 기관에 먼저 연락하세요" },
};
const GENERIC_ERROR = "정리하지 못했어요. 잠시 뒤 다시 시도해 주세요.";
const ADVICE = "사건마다 사정이 달라서 변호사나 대한법률구조공단(132)의 상담이 필요합니다.";

const anchor = (id: string) => `source-${id}`;

export default function Page() {
  const [story, setStory] = useState("");
  const [submitted, setSubmitted] = useState(""); // the story the current result belongs to
  const [result, setResult] = useState<ReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (result) resultRef.current?.focus();
  }, [result]);

  async function request(text: string, role?: Role) {
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_URL}/api/report`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ story: text, role: role ?? null }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        // 422 (the model blocked the text) and 503 (overload, quota) carry a message written for users
        setError([422, 503].includes(response.status) && typeof body?.detail === "string" ? body.detail : GENERIC_ERROR);
        return;
      }
      setResult((await response.json()) as ReportResponse);
      setSubmitted(text);
    } catch {
      setError(GENERIC_ERROR);
    } finally {
      setLoading(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (story.trim().length >= 2) void request(story.trim());
  }

  const changeRole = (role: Role) => void request(submitted, role);

  return (
    <>
      <header className="bar">
        <div className="wrap">
          <span className="name">Lawg</span>
          <p>온라인 사건 법령 정보 안내 · 법률 상담이 아닙니다</p>
        </div>
      </header>

      <main className="wrap" aria-busy={loading}>
        <section className="intake">
          <h1>무슨 일이 있었나요?</h1>
          <p>평소 말투 그대로 적어 주세요. 실명, 계좌번호, 전화번호는 빼고 적어 주세요. 들어가더라도 저장하기 전에 최대한 가립니다.</p>
          <form className="box" onSubmit={onSubmit}>
            <label htmlFor="story" className="srOnly">사건 설명</label>
            <textarea
              id="story"
              value={story}
              maxLength={2000}
              placeholder="예: 메이플 메소 사려고 20만원 보냈는데 먹튀 당했어요. 돈 받자마자 차단하고 잠수 탔어요."
              onChange={(event) => setStory(event.target.value)}
            />
            <div className="boxFoot">
              <span>게임·커뮤니티에서 생긴 사기, 욕설·모욕, 성적 메시지, 계정 도용, 협박을 다룹니다.</span>
              <button className="btn btnMain" type="submit" disabled={loading || story.trim().length < 2}>
                {loading ? "정리하는 중…" : "정리하기"}
              </button>
            </div>
          </form>
          <p className="srOnly" role="status">{loading ? "정리하는 중이에요" : ""}</p>
          {error && <p className="error" role="alert">{error}</p>}
        </section>

        {result && (
          <div ref={resultRef} tabIndex={-1} aria-label="정리 결과">
            <Reading result={result} />
            {result.report ? (
              <Sheet key={result.trace_id} result={result} report={result.report} loading={loading} onRole={changeRole} />
            ) : result.refusal ? (
              <article className="refuse">
                <h2>{REFUSAL[result.refusal.kind].title}</h2>
                <p>{result.refusal.message}</p>
                {result.refusal.alternatives.length > 0 && (
                  <>
                    <h3>대신 알려드릴 수 있는 것</h3>
                    <ul>{result.refusal.alternatives.map((item) => <li key={item}>{item}</li>)}</ul>
                  </>
                )}
                {result.refusal.rephrase && (
                  <>
                    <h3>이렇게 다시 물어보세요</h3>
                    <p>&ldquo;{result.refusal.rephrase}&rdquo;</p>
                  </>
                )}
              </article>
            ) : (
              <section className="ask">
                <h2>어느 쪽 입장인가요?</h2>
                <p>입장에 따라 할 수 있는 일이 달라서 한 번만 여쭤볼게요.</p>
                <RoleChoice current={result.reading.role} disabled={loading} onRole={changeRole} />
              </section>
            )}
          </div>
        )}
      </main>

      <footer className="foot">
        <div className="wrap">
          <p>이 서비스는 공개된 법령 정보를 정리해 보여줍니다. 법률 상담이나 법적 판단을 대신하지 않습니다. 급한 위험이 있으면 112에 신고하세요.</p>
        </div>
      </footer>
    </>
  );
}

function Reading({ result }: { result: ReportResponse }) {
  const { reading, report, refusal, sources } = result;
  const counts = (Object.keys(KIND) as SourceKind[])
    .map((kind) => [KIND[kind], sources.filter((source) => source.kind === kind).length] as const)
    .filter(([, count]) => count > 0)
    .map(([label, count]) => `${label} ${count}`)
    .join(" · ");
  return (
    <section className="read" aria-label="이렇게 읽었어요">
      <h2>이렇게 읽었어요</h2>
      <dl>
        <div><dt>입장</dt><dd>{ROLE[reading.role].reading}</dd></div>
        {reading.terms.length > 0 && (
          <div>
            <dt>쓰신 말 → 법의 말</dt>
            <dd>
              {reading.terms.map((term) => (
                <Fragment key={term.said}>
                  <span className="term">{term.said}</span>
                  <span className="arrow" aria-hidden="true">→</span>
                  {term.legal.map((legal) => <span className="term" key={legal}>{legal}</span>)}
                </Fragment>
              ))}
            </dd>
          </div>
        )}
        <div><dt>찾은 자료</dt><dd>{counts || "없음"}</dd></div>
        <div>
          <dt>근거 확인</dt>
          <dd>
            {report ? (
              <><span className="pass">통과</span> 관련 조문을 찾았어요</>
            ) : refusal ? (
              <><span className="halt">멈춤</span> {REFUSAL[refusal.kind].halt}</>
            ) : (
              <><span className="halt">확인 필요</span> 입장을 골라 주세요</>
            )}
          </dd>
        </div>
      </dl>
    </section>
  );
}

function Sheet({ result, report, loading, onRole }: {
  result: ReportResponse;
  report: Report;
  loading: boolean;
  onRole: (role: Role) => void;
}) {
  const [choosing, setChoosing] = useState(false);
  const [hit, setHit] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const byId = new Map(result.sources.map((source) => [source.id, source]));
  const role = result.reading.role;

  function cite(id: string) {
    setHit(id);
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(anchor(id))?.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(reportText(result, report));
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  const cites = (ids: string[]) =>
    ids.map((id) => (
      <a key={id} className="cite" href={`#${anchor(id)}`} onClick={(event) => { event.preventDefault(); cite(id); }}>
        {id}
      </a>
    ));

  return (
    <>
      <article className="sheet">
        <header className="sheetHead">
          <h2>사건 정리 리포트</h2>
          <p className="sheetMeta">
            {result.reading.category && <span>{CATEGORY[result.reading.category]}</span>}
            <span>{new Intl.DateTimeFormat("ko-KR", { dateStyle: "long" }).format(new Date(result.created_at))} 작성</span>
            <span>근거 자료 {result.sources.length}건</span>
          </p>
          <div className="stance">
            <span><b>{ROLE[role].stance}</b>으로 정리했어요.</span>
            <button className="btn btnText" type="button" aria-expanded={choosing} onClick={() => setChoosing(!choosing)}>
              입장이 다르면 바꾸기
            </button>
          </div>
          {choosing && <RoleChoice current={role} disabled={loading} onRole={onRole} />}
        </header>

        <section className="sec">
          <h3>상황 요약</h3>
          <p>{report.summary}</p>
        </section>

        <section className="sec">
          <h3>관련될 수 있는 조문</h3>
          {report.laws.map((item) => {
            const source = byId.get(item.source);
            if (!source) return null;
            return (
              <div className="law" key={item.source}>
                <div className="lawName">
                  {source.title}
                  {source.case_number && <span className="num">{source.case_number}{source.decided_on && ` · ${source.decided_on}`}</span>}
                  {cites([source.id])}
                </div>
                <blockquote>{source.text}</blockquote>
                <p className="plain"><b>쉬운 말로:</b> {item.plain}</p>
              </div>
            );
          })}
        </section>

        <CitedSection title="처벌 범위 참고" items={report.penalty} render={(claim) => <p key={claim.text}>{claim.text}{cites(claim.sources)}</p>} />

        {report.facts_to_check.length > 0 && (
          <section className="sec">
            <h3>확인이 필요한 사실</h3>
            <ul className="checks">
              {report.facts_to_check.map((fact) => (
                <li key={fact}><label><input type="checkbox" /><span>{fact}</span></label></li>
              ))}
            </ul>
          </section>
        )}

        {report.actions.length > 0 && (
          <section className="sec">
            <h3>지금 할 수 있는 일</h3>
            <ul className="steps">
              {report.actions.map((claim) => <li key={claim.text}>{claim.text}{cites(claim.sources)}</li>)}
            </ul>
          </section>
        )}

        {report.prepare.length > 0 && (
          <section className="sec">
            <h3>준비할 것</h3>
            <ul>{report.prepare.map((item) => <li key={item}>{item}</li>)}</ul>
          </section>
        )}

        <section className="cannot">
          <h3>이 리포트가 답하지 못하는 것</h3>
          {report.cannot_answer.length > 0 && <ul>{report.cannot_answer.map((item) => <li key={item}>{item}</li>)}</ul>}
          <p style={{ margin: "var(--space-sm) 0 0" }}>{ADVICE}</p>
        </section>

        <section className="sources">
          <h3>근거 자료</h3>
          <ol>
            {result.sources.map((source) => (
              <li key={source.id} id={anchor(source.id)} className={hit === source.id ? "isHit" : undefined}>
                <span className="id">{source.id}</span>
                <span>{source.url ? <a href={source.url} target="_blank" rel="noreferrer">{source.title}</a> : source.title}</span>
                <span className="num">{KIND[source.kind]}</span>
              </li>
            ))}
          </ol>
        </section>
      </article>

      <div className="actions">
        <button className="btn" type="button" onClick={() => window.print()}>인쇄 · PDF 저장</button>
        <button className="btn" type="button" onClick={copy}>{copied ? "복사했어요" : "내용 복사"}</button>
      </div>
    </>
  );
}

function CitedSection({ title, items, render }: { title: string; items: Cited[]; render: (claim: Cited) => ReactNode }) {
  if (items.length === 0) return null;
  return (
    <section className="sec">
      <h3>{title}</h3>
      {items.map(render)}
    </section>
  );
}

function RoleChoice({ current, disabled, onRole }: { current: Role; disabled: boolean; onRole: (role: Role) => void }) {
  return (
    <div className="roles" role="group" aria-label="입장 고르기">
      {CHOOSABLE.map((role) => (
        <button
          key={role}
          className="btn"
          type="button"
          aria-pressed={current === role}
          disabled={disabled || current === role}
          onClick={() => onRole(role)}
        >
          {ROLE[role].reading}
        </button>
      ))}
    </div>
  );
}

function reportText(result: ReportResponse, report: Report): string {
  const byId = new Map<string, Source>(result.sources.map((source) => [source.id, source]));
  const cites = (ids: string[]) => (ids.length ? ` [${ids.join(", ")}]` : "");
  const list = (title: string, items: string[]) => (items.length ? [`\n${title}`, ...items.map((item) => `- ${item}`)] : []);
  return [
    "사건 정리 리포트 (Lawg)",
    result.reading.category ? CATEGORY[result.reading.category] : "",
    `${ROLE[result.reading.role].stance}으로 정리`,
    "\n상황 요약",
    report.summary,
    "\n관련될 수 있는 조문",
    ...report.laws.flatMap((item) => {
      const source = byId.get(item.source);
      return source ? [`- ${source.title} [${source.id}]`, `  ${source.text}`, `  쉬운 말로: ${item.plain}`] : [];
    }),
    ...list("처벌 범위 참고", report.penalty.map((claim) => claim.text + cites(claim.sources))),
    ...list("확인이 필요한 사실", report.facts_to_check),
    ...list("지금 할 수 있는 일", report.actions.map((claim) => claim.text + cites(claim.sources))),
    ...list("준비할 것", report.prepare),
    ...list("이 리포트가 답하지 못하는 것", report.cannot_answer),
    ADVICE,
    "\n근거 자료",
    ...result.sources.map((source) => `${source.id} ${source.title} (${KIND[source.kind]})${source.url ? ` ${source.url}` : ""}`),
    "\n법률 상담이 아니라 공개된 법령 정보를 정리한 것입니다.",
  ].filter((line) => line !== "").join("\n");
}
