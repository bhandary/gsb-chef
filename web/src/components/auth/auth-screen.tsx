"use client";

import { FormEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";

export function AuthScreen({
  onAuthenticated,
}: {
  onAuthenticated: (email: string) => void;
}) {
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pending, setPending] = useState(false);

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setNotice("");
    const form = new FormData(event.currentTarget);
    const email = String(form.get("email") || "");
    const password = String(form.get("password") || "");
    setPending(true);
    try {
      const response = await fetch(`/api/auth/${mode}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ email, password }),
      });
      const body = (await response.json().catch(() => ({}))) as {
        error?: string;
        email?: string;
        delivery?: string;
      };
      if (!response.ok) {
        setError(body.error || "Something went wrong.");
        return;
      }
      if (mode === "signup") {
        setNotice(
          body.delivery === "smtp"
            ? "Account created. Open the verification link in your email."
            : "Account created. Open the verification link printed in the auth server log.",
        );
        return;
      }
      onAuthenticated(body.email || email);
    } catch {
      setError("The account server is not running.");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex min-h-screen w-full items-center justify-center p-4">
      <div className="bg-card flex w-full max-w-md flex-col rounded-lg border shadow-lg">
        <div className="flex flex-col gap-2 border-b p-6">
          <h1 className="font-heading text-xl font-semibold tracking-tight">GSB Chef</h1>
          <p className="text-muted-foreground text-sm">
            Create an account and verify your email before asking for recipes.
            Passwords are stored as Argon2id hashes.
          </p>
        </div>
        <form
          onSubmit={onSubmit}
          className="bg-muted/50 flex flex-col gap-4 p-6"
        >
          <div className="flex gap-2">
            <Button
              type="button"
              variant={mode === "signup" ? "default" : "outline"}
              onClick={() => {
                setMode("signup");
                setError("");
                setNotice("");
              }}
            >
              Sign up
            </Button>
            <Button
              type="button"
              variant={mode === "login" ? "default" : "outline"}
              onClick={() => {
                setMode("login");
                setError("");
                setNotice("");
              }}
            >
              Sign in
            </Button>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              name="email"
              type="email"
              autoComplete="email"
              required
              className="bg-card"
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
            <PasswordInput
              id="password"
              name="password"
              autoComplete={mode === "signup" ? "new-password" : "current-password"}
              required
              minLength={8}
              className="bg-card"
            />
          </div>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          {notice ? <p className="text-muted-foreground text-sm">{notice}</p> : null}
          <Button
            type="submit"
            disabled={pending}
          >
            {pending ? "Please wait" : mode === "signup" ? "Create account" : "Sign in"}
          </Button>
        </form>
      </div>
    </div>
  );
}
