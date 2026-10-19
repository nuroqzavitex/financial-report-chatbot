"use client";

import { FileText, SquarePen } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Composer } from "@/components/chat/Composer";
import { MessageList } from "@/components/chat/MessageList";
import { PageViewer } from "@/components/evidence/PageViewer";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetTitle,
} from "@/components/ui/sheet";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useChat } from "@/hooks/useChat";
import type { ClaimDTO } from "@/lib/api/client";

export interface Selection {
  claim: ClaimDTO;
  page: number;
}

export default function Home() {
  const { messages, status, send, reset, busy } = useChat();
  const [selected, setSelected] = useState<Selection | null>(null);
  const wide = useMediaQuery("(min-width: 1024px)");
  const close = () => setSelected(null);

  return (
    <main className="grid h-dvh grid-cols-1 lg:grid-cols-[minmax(0,1fr)_minmax(0,46%)]">
      <section className="flex min-h-0 flex-col">
        <header className="border-rule flex items-center justify-between gap-3 border-b px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-[0.95rem] font-semibold">
              Báo cáo thường niên Techcombank 2025
            </h1>
            <p className="text-ink-soft truncate text-xs">
              Mọi con số được đối chiếu với báo cáo trước khi hiển thị
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              close();
              reset();
            }}
          >
            <SquarePen />
            <span className="max-sm:sr-only">Cuộc trò chuyện mới</span>
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-[44rem] px-4 sm:px-6">
            <MessageList
              messages={messages}
              status={status}
              busy={busy}
              selected={selected}
              onCite={(claim, page) => setSelected({ claim, page })}
              onPick={send}
            />
          </div>
        </div>
        <div className="mx-auto w-full max-w-[44rem] px-4 pt-2 pb-4 sm:px-6">
          <Composer busy={busy} onSend={send} />
        </div>
      </section>
      <aside
        id="page-viewer-slot"
        className="bg-desk border-rule hidden min-h-0 border-l lg:block"
      >
        {wide && selected ? (
          <PageViewer
            claim={selected.claim}
            page={selected.page}
            onClose={close}
          />
        ) : (
          <div className="text-ink-soft flex h-full flex-col items-center justify-center gap-3 px-10 text-center">
            <FileText className="size-10 stroke-[1.25]" aria-hidden />
            <p className="max-w-[26ch] text-sm">
              Bấm vào số trang trong câu trả lời để mở trang báo cáo tại đây.
            </p>
          </div>
        )}
      </aside>
      {!wide && (
        <Sheet open={selected !== null} onOpenChange={(o) => !o && close()}>
          <SheetContent
            side="right"
            showCloseButton={false}
            className="bg-desk gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-xl"
          >
            <SheetTitle className="sr-only">Trang báo cáo</SheetTitle>
            <SheetDescription className="sr-only">
              Trang báo cáo chứa bằng chứng
            </SheetDescription>
            {selected && (
              <PageViewer
                claim={selected.claim}
                page={selected.page}
                onClose={close}
              />
            )}
          </SheetContent>
        </Sheet>
      )}
    </main>
  );
}
