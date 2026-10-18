import type {
  CalcDTO,
  ChatAnswer,
  ClaimDTO,
  SourceDTO,
} from "@/lib/api/client";

type Operand = CalcDTO["operands"][number];

export function op(
  label: string,
  period: string | null,
  raw: string,
  page: number,
  unit = "triệu đồng",
): Operand {
  return {
    fact_id: `f-${label}-${period}`,
    label,
    period,
    raw,
    value: raw.replace(/\./g, ""),
    unit,
    printed_pages: [page],
  };
}

export function claim(
  text: string,
  pages: number[],
  sources?: SourceDTO[],
): ClaimDTO {
  return {
    text,
    printed_pages: pages,
    citation: `[tr. ${pages.join(", ")}]`,
    sources:
      sources ??
      pages.map((p) => ({
        kind: "chunk" as const,
        id: `c${p}`,
        printed_pages: [p],
        evidence: `evidence ${p}`,
      })),
  };
}

export function calc(over: Partial<CalcDTO> = {}): CalcDTO {
  return {
    id: "c1",
    rendered: "tăng 21,82%",
    formula: "(a - b) / b",
    value: "21.82",
    unit: "%",
    operands: [],
    ...over,
  };
}

export function answer(over: Partial<ChatAnswer> = {}): ChatAnswer {
  return {
    session_id: "s1",
    status: "answered",
    text: "Câu trả lời.",
    claims: [],
    notes: [],
    calcs: [],
    conflict_kind: null,
    trace_id: "t1",
    latency_ms: {},
    cost_usd: "0",
    ...over,
  };
}

export function src(
  kind: "fact" | "chunk",
  id: string,
  pages: number[],
  evidence = "",
): SourceDTO {
  return { kind, id, printed_pages: pages, evidence };
}
