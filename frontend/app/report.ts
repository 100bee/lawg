// Mirrors the Lawg report API in backend/app/schemas.py. Change both together.

export type Role = "victim" | "offender" | "third_party" | "unclear";
export type Category = "fraud" | "insult" | "defamation" | "obscenity" | "account" | "threat";
export type RefusalKind = "out_of_scope" | "no_evidence" | "individual_conclusion" | "evasion" | "referral";
export type SourceKind = "statute" | "precedent" | "sentencing" | "guide";

export type ReportRequest = {
  story: string;
  role?: Role | null; // set when the user corrects the inferred role
};

export type Term = { said: string; legal: string[] };

export type Reading = {
  role: Role;
  category: Category | null; // null when the story is out of scope
  terms: Term[];
};

export type Source = {
  id: string; // "S1", "S2", ...
  kind: SourceKind;
  title: string;
  text: string;
  effective_date?: string | null; // YYYY-MM-DD
  case_number?: string | null;
  decided_on?: string | null; // YYYY-MM-DD
  url?: string | null;
};

export type Cited = { text: string; sources: string[] };

export type LawItem = { source: string; plain: string };

export type Report = {
  summary: string;
  laws: LawItem[];
  penalty: Cited[];
  facts_to_check: string[];
  actions: Cited[];
  prepare: string[];
  cannot_answer: string[];
};

export type Refusal = {
  kind: RefusalKind;
  message: string;
  alternatives: string[];
  rephrase?: string | null;
};

// Exactly one of report / refusal is set, unless reading.role is "unclear" (the UI then asks for the role).
export type ReportResponse = {
  reading: Reading;
  report: Report | null;
  refusal: Refusal | null;
  sources: Source[];
  trace_id: string;
  created_at: string;
};
