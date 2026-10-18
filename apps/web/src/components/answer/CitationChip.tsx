import { Button } from "@/components/ui/button";

export function CitationChip({
  page,
  onClick,
}: {
  page: number;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      variant="outline"
      size="xs"
      aria-label={`Xem trang ${page}`}
      onClick={onClick}
    >
      tr. {page}
    </Button>
  );
}
