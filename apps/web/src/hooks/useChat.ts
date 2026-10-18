"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { streamChat, type ChatAnswer } from "@/lib/api/client";

export type ChatItem =
  | { role: "user"; text: string }
  | { role: "assistant"; answer: ChatAnswer }
  | { role: "error"; text: string };

export function useChat() {
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  // In memory only: the transcript is not persisted, so a reload must not silently carry the
  // previous server-side history into the next question.
  const sessionRef = useRef<string | undefined>(undefined);

  const finish = useCallback(() => {
    busyRef.current = false;
    abortRef.current = null;
    setBusy(false);
    setStatus(null);
  }, []);

  const send = useCallback(
    (text: string) => {
      const message = text.trim();
      if (!message || busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setMessages((m) => [...m, { role: "user", text: message }]);
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const live = () => abortRef.current === ctrl;
      void streamChat(
        { session_id: sessionRef.current, message },
        {
          onStatus: (s) => {
            if (live()) setStatus(s.label);
          },
          onAnswer: (answer) => {
            if (!live()) return;
            sessionRef.current = answer.session_id;
            setMessages((m) => [...m, { role: "assistant", answer }]);
            finish();
          },
          onError: (msg) => {
            if (!live()) return;
            setMessages((m) => [...m, { role: "error", text: msg }]);
            finish();
          },
        },
        ctrl.signal,
      );
    },
    [finish],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    sessionRef.current = undefined;
    setMessages([]);
    finish();
  }, [finish]);

  useEffect(() => () => abortRef.current?.abort(), []);

  return { messages, status, send, reset, busy };
}
