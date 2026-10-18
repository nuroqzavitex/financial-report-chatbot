import { Loader2 } from "lucide-react";

export function StatusStream({ status }: { status: string | null }) {
  return (
    <div
      role="status"
      aria-live="polite"
      className="text-muted-foreground flex items-center gap-2 text-sm"
    >
      <Loader2 className="size-4 animate-spin" aria-hidden />
      <span>{status ?? "Đang xử lý…"}</span>
    </div>
  );
}
