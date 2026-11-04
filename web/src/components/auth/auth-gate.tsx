"use client";

import { ReactNode, useEffect, useState } from "react";
import { AuthScreen } from "@/components/auth/auth-screen";

export function AuthGate({ children }: { children: ReactNode }) {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/auth/me")
      .then(async (response) => {
        if (!response.ok) return null;
        const body = (await response.json()) as { email?: string };
        return body.email || null;
      })
      .catch(() => null)
      .then((value) => {
        if (!cancelled) {
          setEmail(value);
          setReady(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!ready) {
    return (
      <div className="text-muted-foreground flex min-h-screen items-center justify-center">
        Loading…
      </div>
    );
  }
  if (!email) {
    return <AuthScreen onAuthenticated={setEmail} />;
  }
  return children;
}
