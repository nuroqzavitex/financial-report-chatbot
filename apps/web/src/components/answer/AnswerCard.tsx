import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { ChatAnswer, ClaimDTO } from "@/lib/api/client";
import { CalcChip } from "./CalcChip";
import { CitationChip } from "./CitationChip";
import { CopyButton } from "./CopyButton";

const STATUS: Record<
  ChatAnswer["status"],
  {
    label: string;
    variant: "default" | "secondary" | "outline" | "destructive";
  }
> = {
  answered: { label: "Đã xác minh", variant: "default" },
  partial: { label: "Một phần", variant: "secondary" },
  refused: { label: "Không tìm thấy", variant: "outline" },
  error: { label: "Lỗi", variant: "destructive" },
};

export function AnswerCard({
  answer,
  onCite,
}: {
  answer: ChatAnswer;
  onCite: (claim: ClaimDTO, page: number) => void;
}) {
  const badge = STATUS[answer.status];
  const bare = answer.claims.length === 0 && answer.notes.length === 0;
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <Badge variant={badge.variant}>{badge.label}</Badge>
          <CopyButton text={answer.text} />
        </div>
        {answer.claims.map((c, i) => (
          <div key={i} className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span>{c.text}</span>
            {c.printed_pages.map((p) => (
              <CitationChip key={p} page={p} onClick={() => onCite(c, p)} />
            ))}
          </div>
        ))}
        {bare && <p>{answer.text}</p>}
        {answer.notes.map((n, i) => (
          <p key={i} className="text-muted-foreground text-sm">
            {n}
          </p>
        ))}
        {answer.calcs.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {answer.calcs.map((c) => (
              <CalcChip key={c.id} calc={c} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
