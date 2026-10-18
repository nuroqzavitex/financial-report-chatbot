"use client";

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
    <main className="mx-auto grid h-screen max-w-7xl grid-cols-1 lg:grid-cols-2">
      <section className="flex min-h-0 flex-col p-4">
        <header className="flex items-center justify-between pb-2">
          <h1 className="font-semibold">
            Báo cáo thường niên Techcombank 2025
          </h1>
          <Button type="button" variant="ghost" size="sm" onClick={reset}>
            Cuộc trò chuyện mới
          </Button>
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <MessageList
            messages={messages}
            status={status}
            busy={busy}
            onCite={(claim, page) => setSelected({ claim, page })}
            onPick={send}
          />
        </div>
        <Composer busy={busy} onSend={send} />
      </section>
      <aside id="page-viewer-slot" className="hidden min-h-0 border-l lg:block">
        {wide && selected && (
          <PageViewer
            claim={selected.claim}
            page={selected.page}
            onClose={close}
          />
        )}
      </aside>
      {!wide && (
        <Sheet open={selected !== null} onOpenChange={(o) => !o && close()}>
          <SheetContent side="right" showCloseButton={false}>
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
