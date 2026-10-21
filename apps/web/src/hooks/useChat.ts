"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getSession,
  NotFound,
  streamChat,
  type ChatAnswer,
  type StoredMessage,
} from "@/lib/api/client";
import { lastSession, rememberSession } from "@/lib/lastSession";

export type ChatItem =
  | { role: "user"; text: string }
  | { role: "assistant"; answer: ChatAnswer }
  // an assistant turn stored before answers were kept whole: its verified text only
  | { role: "legacy"; text: string }
  | { role: "error"; text: string };

function toItem(m: StoredMessage): ChatItem {
  if (m.role === "user") return { role: "user", text: m.content };
  return m.answer
    ? { role: "assistant", answer: m.answer }
    : { role: "legacy", text: m.content };
}

export function useChat({ onSaved }: { onSaved?: () => void } = {}) {
  const [messages, setMessages] = useState<ChatItem[]>([]);
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  // the session the next question continues; null starts a new one on the server
  const sessionRef = useRef<string | null>(null);
  const savedRef = useRef(onSaved);
  useEffect(() => {
    savedRef.current = onSaved;
  }, [onSaved]);

  const select = useCallback((id: string | null) => {
    sessionRef.current = id;
    setSessionId(id);
    rememberSession(id);
  }, []);

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
        { session_id: sessionRef.current ?? undefined, message },
        {
          onStatus: (s) => {
            if (live()) setStatus(s.label);
          },
          onAnswer: (answer) => {
            if (!live()) return;
            select(answer.session_id);
            setMessages((m) => [...m, { role: "assistant", answer }]);
            finish();
            if (answer.status !== "error") savedRef.current?.();
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
    [finish, select],
  );

  const reset = useCallback(() => {
    abortRef.current?.abort();
    select(null);
    setMessages([]);
    finish();
  }, [finish, select]);

  /** Load a stored conversation; the next question continues it. */
  const open = useCallback(
    async (id: string) => {
      abortRef.current?.abort();
      finish();
      select(id);
      setMessages([]);
      try {
        const s = await getSession(id);
        if (sessionRef.current !== id) return; // another session was picked meanwhile
        setMessages(s.messages.map(toItem));
      } catch (e) {
        if (sessionRef.current !== id) return;
        select(null);
        if (!(e instanceof NotFound))
          setMessages([
            { role: "error", text: "Không tải được cuộc trò chuyện." },
          ]);
      }
    },
    [finish, select],
  );

  // reopen the conversation this browser had open before a reload
  useEffect(() => {
    const id = lastSession();
    if (id) void open(id);
  }, [open]);

  useEffect(() => () => abortRef.current?.abort(), []);

  return { messages, status, send, reset, open, busy, sessionId };
}
