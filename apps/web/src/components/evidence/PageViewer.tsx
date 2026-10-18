"use client";

import { X } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { pageImageUrl, type ClaimDTO } from "@/lib/api/client";

export function PageViewer({
  claim,
  page,
  onClose,
}: {
  claim: ClaimDTO;
  page: number;
  onClose: () => void;
}) {
  const source = claim.sources.find((s) => s.printed_pages.includes(page));
  const key = `${page}|${claim.text}`;
  const [failedKey, setFailedKey] = useState<string | null>(null);
  const failed = failedKey === key;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <h2 className="font-semibold">Trang {page}</h2>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label="Đóng"
          onClick={onClose}
        >
          <X />
        </Button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-4">
        {failed ? (
          <div className="space-y-2 text-sm">
            {source?.evidence && (
              <blockquote className="border-l-2 pl-3 italic">
                {source.evidence}
              </blockquote>
            )}
            <p className="text-muted-foreground">
              Không hiển thị được trang (thiếu file PDF trên máy chủ).
            </p>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={key}
            alt={`Trang ${page}`}
            src={pageImageUrl(page, source)}
            className="h-auto w-full"
            onError={() => setFailedKey(key)}
          />
        )}
      </div>
    </div>
  );
}
