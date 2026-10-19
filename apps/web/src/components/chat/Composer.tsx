"use client";

import { ArrowUp } from "lucide-react";
import { useState } from "react";

export function Composer({
  busy,
  onSend,
}: {
  busy: boolean;
  onSend: (text: string) => void;
}) {
  const [value, setValue] = useState("");

  function submit() {
    const text = value.trim();
    if (!text || busy) return;
    onSend(text);
    setValue("");
  }

  return (
    <form
      className="bg-card border-input focus-within:border-pencil focus-within:ring-pencil/15 flex items-end gap-2 rounded-xl border p-2 pl-4 shadow-[0_1px_2px_rgb(29_43_52/0.06)] focus-within:ring-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <textarea
        aria-label="Câu hỏi"
        placeholder="Hỏi về số liệu, chỉ tiêu, chiến lược…"
        rows={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        className="placeholder:text-ink-soft/80 field-sizing-content max-h-40 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-[0.95rem] outline-none"
      />
      <button
        type="submit"
        aria-label="Gửi"
        disabled={busy || !value.trim()}
        className="bg-ink text-primary-foreground hover:bg-pencil focus-visible:ring-pencil/40 disabled:bg-muted disabled:text-ink-soft inline-flex size-9 shrink-0 items-center justify-center rounded-lg outline-none focus-visible:ring-3"
      >
        <ArrowUp className="size-4" aria-hidden />
      </button>
    </form>
  );
}
