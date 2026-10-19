import { cn } from "cn";

export function CitationChip({
  page,
  active = false,
  onClick,
}: {
  page: number;
  active?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={`Xem trang ${page}`}
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "text-pencil focus-visible:ring-pencil/40 inline-flex h-6 items-center rounded-md border border-current/25 px-1.5 text-xs font-medium whitespace-nowrap outline-none focus-visible:ring-3",
        active ? "bg-pencil text-card border-pencil" : "hover:bg-pencil-wash",
      )}
    >
      tr. {page}
    </button>
  );
}
