"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

export default function VerifyPage() {
  const router = useRouter();
  const [message, setMessage] = useState("Verifying your email…");
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    const params = new URLSearchParams(window.location.hash.replace(/^#/, ""));
    const token = params.get("token") || "";
    window.history.replaceState(null, "", "/verify");
    if (!token) {
      setMessage("This verification link is invalid.");
      return;
    }
    started.current = true;
    fetch("/api/auth/verify", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token }),
    })
      .then(async (response) => {
        const body = (await response.json().catch(() => ({}))) as {
          error?: string;
        };
        if (!response.ok) {
          setMessage(body.error || "This verification link is invalid.");
          return;
        }
        router.replace("/");
      })
      .catch(() => {
        setMessage("The account server is not running.");
      });
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <p className="text-muted-foreground max-w-md text-center text-sm">{message}</p>
    </div>
  );
}
