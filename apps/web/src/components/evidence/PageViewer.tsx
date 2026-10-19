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
      <div className="border-rule bg-paper/70 flex items-start justify-between gap-3 border-b px-5 py-3">
        <div className="min-w-0">
          <h2 className="font-semibold">Trang {page}</h2>
          <p className="text-ink-soft line-clamp-2 font-serif text-sm">
            {claim.text}
          </p>
        </div>
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
      <div className="min-h-0 flex-1 overflow-auto p-4 sm:p-6">
        {failed ? (
          <div className="bg-card space-y-3 rounded-lg p-5 text-sm">
            {source?.evidence && (
              <blockquote className="border-pencil border-l-2 pl-3 font-serif text-base">
                {source.evidence}
              </blockquote>
            )}
            <p className="text-ink-soft">
              Không hiển thị được trang (thiếu file PDF trên máy chủ).
            </p>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            key={key}
            alt={`Trang ${page}`}
            src={pageImageUrl(page, source)}
            className="mx-auto h-auto w-full max-w-[52rem] rounded-sm shadow-[0_1px_3px_rgb(29_43_52/0.18),0_12px_32px_-8px_rgb(29_43_52/0.25)]"
            onError={() => setFailedKey(key)}
          />
        )}
      </div>
    </div>
  );
}
