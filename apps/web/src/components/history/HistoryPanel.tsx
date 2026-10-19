"use client";

import { SquarePen, Trash2 } from "lucide-react";
import { cn } from "cn";
import type { SessionSummary } from "@/lib/api/client";

const TIME = new Intl.DateTimeFormat("vi-VN", {
  hour: "2-digit",
  minute: "2-digit",
});
const DAY = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
});

/** "14:05" today, "Hôm qua", else the date. */
export function whenLabel(iso: string, now = new Date()): string {
  const t = new Date(iso);
  const days = Math.round(
    (new Date(now.toDateString()).getTime() -
      new Date(t.toDateString()).getTime()) /
      86_400_000,
  );
  if (days <= 0) return TIME.format(t);
  if (days === 1) return "Hôm qua";
  return DAY.format(t);
}

export function HistoryPanel({
  sessions,
  activeId,
  failed,
  onOpen,
  onNew,
  onDelete,
  onRetry,
}: {
  sessions: SessionSummary[];
  activeId: string | null;
  failed: boolean;
  onOpen: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onRetry: () => void;
}) {
  return (
    <nav
      aria-label="Lịch sử trò chuyện"
      className="flex h-full min-h-0 flex-col"
    >
      <div className="p-3">
        <button
          type="button"
          onClick={onNew}
          className="bg-card border-rule hover:border-pencil hover:text-pencil focus-visible:ring-pencil/40 flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-sm font-medium outline-none focus-visible:ring-3"
        >
          <SquarePen className="size-4" aria-hidden />
          Cuộc trò chuyện mới
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {failed ? (
          <div className="text-ink-soft px-2 py-3 text-sm">
            <p>Không tải được lịch sử.</p>
            <button
              type="button"
              onClick={onRetry}
              className="text-pencil mt-1 underline-offset-2 hover:underline"
            >
              Thử lại
            </button>
          </div>
        ) : sessions.length === 0 ? (
          <p className="text-ink-soft px-2 py-3 text-sm leading-relaxed">
            Chưa có cuộc trò chuyện nào. Câu hỏi đầu tiên của bạn sẽ được lưu ở
            đây.
          </p>
        ) : (
          <ul className="space-y-0.5">
            {sessions.map((s) => {
              const active = s.id === activeId;
              return (
                <li key={s.id} className="group relative">
                  <button
                    type="button"
                    onClick={() => onOpen(s.id)}
                    aria-current={active ? "true" : undefined}
                    className={cn(
                      "focus-visible:ring-pencil/40 flex w-full flex-col items-start gap-0.5 rounded-md border-l-2 py-2 pr-9 pl-3 text-left outline-none focus-visible:ring-3",
                      active
                        ? "border-pencil bg-card"
                        : "hover:bg-card/70 border-transparent",
                    )}
                  >
                    <span className="line-clamp-2 text-sm leading-snug">
                      {s.title || "Cuộc trò chuyện"}
                    </span>
                    <span className="text-ink-soft text-xs">
                      {whenLabel(s.updated_at)}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Xoá “${s.title}”`}
                    onClick={() => {
                      if (window.confirm("Xoá cuộc trò chuyện này?"))
                        onDelete(s.id);
                    }}
                    className="text-ink-soft hover:text-destructive focus-visible:ring-pencil/40 absolute top-2 right-1.5 rounded-md p-1.5 opacity-0 outline-none group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-3 [@media(hover:none)]:opacity-100"
                  >
                    <Trash2 className="size-3.5" aria-hidden />
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </nav>
  );
}
