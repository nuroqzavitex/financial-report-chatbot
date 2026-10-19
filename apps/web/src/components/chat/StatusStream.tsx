import { Loader2 } from "lucide-react";

export function StatusStream({ status }: { status: string | null }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="bg-card border-rule text-ink-soft flex items-center gap-2.5 rounded-lg border border-dashed px-4 py-3 text-sm"
    >
      <Loader2 className="text-pencil size-4 animate-spin" aria-hidden />
      <span>{status ?? "Đang xử lý…"}</span>
    </div>
  );
}
