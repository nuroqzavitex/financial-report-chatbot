import { Check, CircleAlert, CircleDashed, SearchX } from "lucide-react";
import type { ChatAnswer, ClaimDTO } from "@/lib/api/client";
import { CalcChip } from "./CalcChip";
import { CitationChip } from "./CitationChip";
import { CopyButton } from "./CopyButton";

// the left rule and the status line both say how much of the answer survived the verifier
const STATUS: Record<
  ChatAnswer["status"],
  { label: string; icon: typeof Check; tone: string; rule: string }
> = {
  answered: {
    label: "Đã xác minh",
    icon: Check,
    tone: "text-tick bg-tick-wash",
    rule: "border-l-tick",
  },
  partial: {
    label: "Một phần",
    icon: CircleDashed,
    tone: "text-caution bg-caution-wash",
    rule: "border-l-caution",
  },
  refused: {
    label: "Không tìm thấy",
    icon: SearchX,
    tone: "text-ink-soft bg-muted",
    rule: "border-l-ink-soft/50",
  },
  error: {
    label: "Lỗi",
    icon: CircleAlert,
    tone: "text-destructive bg-destructive/10",
    rule: "border-l-destructive",
  },
};

export function AnswerCard({
  answer,
  selected = null,
  onCite,
}: {
  answer: ChatAnswer;
  selected?: { claim: ClaimDTO; page: number } | null;
  onCite: (claim: ClaimDTO, page: number) => void;
}) {
  const s = STATUS[answer.status];
  const Icon = s.icon;
  const bare = answer.claims.length === 0 && answer.notes.length === 0;
  return (
    <article
      className={`bg-card border-rule rounded-lg border border-l-[3px] ${s.rule}`}
    >
      <div className="flex items-center justify-between gap-2 px-4 pt-3 sm:px-5">
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${s.tone}`}
        >
          <Icon className="size-3.5" aria-hidden />
          {s.label}
        </span>
        <CopyButton text={answer.text} />
      </div>

      {answer.claims.length > 0 && (
        <ul className="px-4 pt-2 pb-1 sm:px-5">
          {answer.claims.map((c, i) => (
            <li
              key={i}
              className="border-rule grid grid-cols-[1rem_minmax(0,1fr)_auto] items-baseline gap-x-3 border-b border-dashed py-2.5 last:border-b-0"
            >
              <Check
                className="text-tick size-4 translate-y-0.5 self-start"
                aria-hidden
              />
              <span className="font-serif text-[1.05rem] leading-relaxed">
                {c.text}
              </span>
              <span className="flex flex-wrap justify-end gap-1">
                {c.printed_pages.map((p) => (
                  <CitationChip
                    key={p}
                    page={p}
                    active={selected?.claim === c && selected.page === p}
                    onClick={() => onCite(c, p)}
                  />
                ))}
              </span>
            </li>
          ))}
        </ul>
      )}

      {bare && (
        <p className="px-4 py-3 font-serif text-[1.05rem] leading-relaxed sm:px-5">
          {answer.text}
        </p>
      )}

      {answer.calcs.length > 0 && (
        <div className="px-4 pt-1 pb-3 sm:px-5">
          <p className="text-ink-soft mb-1.5 text-xs">
            Phép tính, bấm để xem công thức và số liệu đầu vào
          </p>
          <div className="flex flex-wrap gap-2">
            {answer.calcs.map((c) => (
              <CalcChip key={c.id} calc={c} />
            ))}
          </div>
        </div>
      )}

      {answer.notes.length > 0 && (
        <div className="border-rule text-ink-soft space-y-1 border-t px-4 py-3 text-sm leading-relaxed sm:px-5">
          {answer.notes.map((n, i) => (
            <p key={i}>{n}</p>
          ))}
        </div>
      )}
      {!bare && answer.notes.length === 0 && <div className="h-2" />}
    </article>
  );
}
