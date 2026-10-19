"use client";

import { useCallback, useEffect, useState } from "react";
import {
  deleteSession,
  listSessions,
  type SessionSummary,
} from "@/lib/api/client";

/** This browser's stored conversations, newest first. */
export function useSessions() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [failed, setFailed] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setSessions(await listSessions());
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  const remove = useCallback(
    async (id: string) => {
      setSessions((list) => list.filter((s) => s.id !== id));
      try {
        await deleteSession(id);
      } catch {
        /* the refresh below brings the session back */
      }
      void refresh();
    },
    [refresh],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { sessions, failed, refresh, remove };
}
