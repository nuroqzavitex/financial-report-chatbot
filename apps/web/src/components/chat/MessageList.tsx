"use client";

import { useEffect, useRef } from "react";
import { AnswerCard } from "@/components/answer/AnswerCard";
import type { ClaimDTO } from "@/lib/api/client";
import type { ChatItem } from "@/hooks/useChat";
import { StatusStream } from "./StatusStream";

const EXAMPLES = [
  "Tổng tài sản năm 2025?",
  "Dư nợ vay RBG tăng bao nhiêu?",
  "RBG là viết tắt của gì?",
];

export function MessageList({
  messages,
  status,
  busy,
  onCite,
  onPick,
}: {
  messages: ChatItem[];
  status: string | null;
  busy: boolean;
  onCite: (claim: ClaimDTO, page: number) => void;
  onPick: (text: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [messages, busy]);

  if (messages.length === 0 && !busy) {
    return (
      <div className="space-y-3 py-8">
        <p className="text-muted-foreground">Thử hỏi:</p>
        <div className="flex flex-col items-start gap-2">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              className="hover:bg-muted rounded-lg border px-3 py-1.5 text-sm"
              onClick={() => onPick(q)}
            >
              {q}
            </button>
          ))}
        </div>
      </div>
    );
  }
  return (
    <div className="space-y-4 py-4">
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="flex justify-end">
            <p className="bg-primary text-primary-foreground max-w-[85%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap">
              {m.text}
            </p>
          </div>
        ) : m.role === "assistant" ? (
          <AnswerCard key={i} answer={m.answer} onCite={onCite} />
        ) : (
          <p key={i} role="alert" className="text-destructive text-sm">
            {m.text}
          </p>
        ),
      )}
      {busy && <StatusStream status={status} />}
      <div ref={endRef} />
    </div>
  );
}
