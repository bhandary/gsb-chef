"use client";

import { useState } from "react";
import { ThumbsDown, ThumbsUp } from "lucide-react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";
import { TooltipIconButton } from "../tooltip-icon-button";

const UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function asTraceId(value: unknown): string | null {
  return typeof value === "string" && UUID_RE.test(value) ? value : null;
}

function messagesOf(state: unknown): Array<{ id?: unknown }> {
  if (!state || typeof state !== "object") return [];
  const values = (state as { values?: { messages?: unknown } }).values;
  const messages = values?.messages;
  return Array.isArray(messages) ? (messages as Array<{ id?: unknown }>) : [];
}

function stepOf(state: unknown): number {
  const step = (state as { metadata?: { step?: unknown } } | undefined)?.metadata
    ?.step;
  return typeof step === "number" ? step : 0;
}

export function traceIdForAssistantMessage({
  messageId,
  liveRunId,
  history,
  streamRunId,
}: {
  messageId: string | undefined;
  liveRunId: unknown;
  history: unknown[];
  streamRunId: unknown;
}): string | null {
  const live = asTraceId(liveRunId);
  if (live) return live;
  const containing = history
    .filter((state) => messagesOf(state).some((message) => message.id === messageId))
    .slice()
    .sort((left, right) => stepOf(left) - stepOf(right));
  for (const state of containing) {
    const runId = asTraceId(
      (state as { metadata?: { run_id?: unknown } }).metadata?.run_id,
    );
    if (runId) return runId;
  }
  return asTraceId(streamRunId);
}

type Reaction = "liked" | "disliked";

export function MessageFeedback({
  traceId,
  disabled,
}: {
  traceId: string;
  disabled: boolean;
}) {
  const [reaction, setReaction] = useState<Reaction | null>(null);
  const [pending, setPending] = useState(false);

  const choose = async (next: Reaction) => {
    if (pending || disabled) return;
    if (reaction === next) {
      setReaction(null);
      return;
    }
    const previous = reaction;
    setReaction(next);
    setPending(true);
    try {
      const response = await fetch("/api/feedback", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ reaction: next, trace_id: traceId }),
      });
      const body = (await response.json().catch(() => ({}))) as {
        error?: string;
        logged?: boolean;
      };
      if (!response.ok || body.logged !== true) {
        setReaction(previous);
        toast.error("Could not save feedback", {
          description: body.error || "The recipe server did not save this reaction.",
        });
      }
    } catch {
      setReaction(previous);
      toast.error("Could not save feedback", {
        description: "The account server is not running.",
      });
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <TooltipIconButton
        tooltip="Thumbs up"
        variant="ghost"
        aria-pressed={reaction === "liked"}
        disabled={disabled || pending}
        onClick={() => void choose("liked")}
        className={cn(
          reaction === "liked" &&
            "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground",
        )}
      >
        <ThumbsUp className={reaction === "liked" ? "fill-current" : undefined} />
      </TooltipIconButton>
      <TooltipIconButton
        tooltip="Thumbs down"
        variant="ghost"
        aria-pressed={reaction === "disliked"}
        disabled={disabled || pending}
        onClick={() => void choose("disliked")}
        className={cn(
          reaction === "disliked" &&
            "bg-primary text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground",
        )}
      >
        <ThumbsDown
          className={reaction === "disliked" ? "fill-current" : undefined}
        />
      </TooltipIconButton>
    </div>
  );
}
