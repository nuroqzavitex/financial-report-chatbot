"use client";

import { CornerDownRight } from "lucide-react";
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
  selected = null,
  onCite,
  onPick,
}: {
  messages: ChatItem[];
  status: string | null;
  busy: boolean;
  selected?: { claim: ClaimDTO; page: number } | null;
  onCite: (claim: ClaimDTO, page: number) => void;
  onPick: (text: string) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end", behavior: "smooth" });
  }, [messages, busy]);

  if (messages.length === 0 && !busy) {
    return (
      <div className="pt-[12vh] pb-8">
        <h2 className="font-serif text-[1.75rem] leading-tight font-medium text-balance sm:text-[2rem]">
          Hỏi bất cứ điều gì về báo cáo thường niên 2025.
        </h2>
        <p className="text-ink-soft mt-3 max-w-[56ch] leading-relaxed">
          Câu trả lời chỉ giữ lại những con số tìm thấy trong báo cáo, kèm số
          trang để bạn mở ra kiểm tra. Ý nào không đối chiếu được sẽ bị bỏ đi.
        </p>
        <ul className="border-rule mt-8 border-t">
          {EXAMPLES.map((q) => (
            <li key={q} className="border-rule border-b">
              <button
                type="button"
                className="group hover:text-pencil focus-visible:text-pencil flex w-full items-center gap-3 py-3 text-left outline-none"
                onClick={() => onPick(q)}
              >
                <CornerDownRight
                  className="text-ink-soft group-hover:text-pencil size-4 shrink-0"
                  aria-hidden
                />
                <span className="group-focus-visible:underline">{q}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    );
  }
  return (
    <div className="space-y-6 py-6">
      {messages.map((m, i) =>
        m.role === "user" ? (
          <div key={i} className="flex justify-end">
            <p className="bg-ink text-primary-foreground max-w-[85%] rounded-2xl rounded-br-md px-4 py-2.5 text-[0.95rem] whitespace-pre-wrap">
              {m.text}
            </p>
          </div>
        ) : m.role === "assistant" ? (
          <AnswerCard
            key={i}
            answer={m.answer}
            selected={selected}
            onCite={onCite}
          />
        ) : (
          <p
            key={i}
            role="alert"
            className="border-destructive/40 text-destructive rounded-lg border px-4 py-3 text-sm"
          >
            {m.text}
          </p>
        ),
      )}
      {busy && <StatusStream status={status} />}
      <div ref={endRef} />
    </div>
  );
}
