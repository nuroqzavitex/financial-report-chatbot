"use client";

import { SignInButton, useAuth } from "@clerk/nextjs";
import { LogIn } from "lucide-react";
import { Fragment, type ReactNode } from "react";
import { AUTH_ENABLED, setTokenSource } from "@/lib/auth";

/** Without Clerk the app is open; with it, the chat appears only once signed in. */
export function AuthGate({ children }: { children: ReactNode }) {
  if (!AUTH_ENABLED) return <>{children}</>;
  return <ClerkGate>{children}</ClerkGate>;
}

function ClerkGate({ children }: { children: ReactNode }) {
  const { isLoaded, isSignedIn, userId, getToken } = useAuth();
  // Set during render, not in an effect: the chat's own effects (history, the reopened session)
  // run before a parent's effects and must already carry the token.
  setTokenSource(isSignedIn ? () => getToken() : null);

  if (!isLoaded) {
    return (
      <main className="text-ink-soft grid h-dvh place-items-center text-sm">
        Đang kiểm tra đăng nhập…
      </main>
    );
  }
  if (!isSignedIn) return <SignInScreen />;
  // a different account remounts the chat: its history and open session are that user's
  return <Fragment key={userId}>{children}</Fragment>;
}

function SignInScreen() {
  return (
    <main className="grid h-dvh place-items-center px-4">
      <div className="w-full max-w-md">
        <p className="text-ink-soft text-sm">
          Báo cáo thường niên Techcombank 2025
        </p>
        <h1 className="mt-2 font-serif text-[1.9rem] leading-tight font-medium text-balance">
          Đăng nhập để hỏi đáp về báo cáo.
        </h1>
        <p className="text-ink-soft mt-3 leading-relaxed">
          Lịch sử trò chuyện được lưu theo tài khoản, nên bạn mở lại được trên
          mọi thiết bị và người khác không xem được.
        </p>
        <SignInButton mode="modal">
          <button
            type="button"
            className="bg-ink text-primary-foreground hover:bg-pencil focus-visible:ring-pencil/40 mt-8 inline-flex items-center gap-2 rounded-lg px-4 py-2.5 text-sm font-medium outline-none focus-visible:ring-3"
          >
            <LogIn className="size-4" aria-hidden />
            Đăng nhập
          </button>
        </SignInButton>
      </div>
    </main>
  );
}
