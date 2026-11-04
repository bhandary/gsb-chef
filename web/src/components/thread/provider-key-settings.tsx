"use client";

import { FormEvent, useState } from "react";
import { Settings } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { PasswordInput } from "@/components/ui/password-input";
import { useProviderKeys } from "@/providers/Stream";

export function ProviderKeySettings() {
  const { apiUrl, keys, setKeys } = useProviderKeys();
  const [open, setOpen] = useState(false);

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setKeys({
      openai: String(form.get("openai") || ""),
      tavily: String(form.get("tavily") || ""),
    });
    setOpen(false);
  };

  return (
    <>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="API key settings"
        onClick={() => setOpen(true)}
      >
        <Settings className="size-5" />
      </Button>
      {open ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <form
            onSubmit={onSubmit}
            className="bg-card flex w-full max-w-md flex-col gap-4 rounded-lg border p-6 shadow-lg"
          >
            <div className="flex flex-col gap-1">
              <h2 className="text-lg font-semibold">Recipe API keys</h2>
              <p className="text-muted-foreground text-sm">
                These keys are kept in this browser&apos;s localStorage for{" "}
                {apiUrl}. Each chat request sends them to the local agent. The
                server does not write them to its database. Leave a field blank
                to use the matching environment variable instead.
              </p>
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="openai">OpenAI API key</Label>
              <PasswordInput
                id="openai"
                name="openai"
                defaultValue={keys.openai}
                autoComplete="off"
                placeholder="sk-..."
                className="bg-card"
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="tavily">Tavily API key</Label>
              <PasswordInput
                id="tavily"
                name="tavily"
                defaultValue={keys.tavily}
                autoComplete="off"
                placeholder="tvly-..."
                className="bg-card"
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit">Save</Button>
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}

export function LogoutButton() {
  const [pending, setPending] = useState(false);
  return (
    <Button
      type="button"
      variant="outline"
      disabled={pending}
      onClick={() => {
        setPending(true);
        fetch("/api/auth/logout", { method: "POST" }).finally(() => {
          window.location.assign("/");
        });
      }}
    >
      Sign out
    </Button>
  );
}
