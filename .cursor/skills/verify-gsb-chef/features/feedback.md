# Thumbs feedback

A signed-in user marks a finished chef reply thumbs up or thumbs down. The click is sent to the auth server, which calls LangSmith only when tracing and an API key are configured.

## Sub-features

- `feedback-buttons` shows Thumbs up and Thumbs down under a completed assistant message that has a LangGraph run id.
- `feedback-request` posts `{ reaction, trace_id }` to `/api/feedback` and keeps the session cookie on that request.
- `feedback-clear` a second click on the selected thumb clears the highlight and does not send another request.
- `feedback-unconfigured` when `LANGSMITH_TRACING` is not true or `LANGSMITH_API_KEY` is empty, the server responds `503` with `{"error":"feedback not configured"}` and the highlight returns to unselected.

## How to get to it (user POV)

- Sign in so the chat is visible.
- Open a thread whose assistant message was produced by a LangGraph run, or a thread whose checkpoint metadata `run_id` is that run's id.
- The thumbs sit under the reply, next to the copy and refresh actions. Copy and refresh stay hidden until hover. The thumbs stay visible.

## Driving it with Playwright

Preconditions:

- `DOCTOR OK`, and a verified session in this browser context.
- The assistant message is already in the thread. This feature does not require an OpenAI or Tavily key. Seed the thread through the LangGraph state API and make sure `metadata.run_id` on the checkpoint is a UUID. That is the value the UI sends as `trace_id`.
- Do not put `LANGSMITH_API_KEY` into the page, a screenshot, or a log.

- **Open the thread.** Go to `/?threadId=<id>` and wait for the assistant text.
- **See both thumbs.** Wait for the buttons `Thumbs up` and `Thumbs down`. Neither has `aria-pressed="true"`. Screenshot that state.
- **Click one.** Click `Thumbs up`. Read the `POST /api/feedback` request body and the response status and body.
- **Selected state.** When the response is `200` and `logged` is true, the button stays pressed. Screenshot it. When the response is `feedback not configured`, the button returns to unpressed and a toast says `Could not save feedback`. To screenshot the pressed style without a LangSmith key, fulfill a later `/api/feedback` response as `200` `{"ok":true,"logged":true}` and click again.
- **Clear.** Click the same thumb again. No further `/api/feedback` request is sent, and `aria-pressed` is false.
- **Signed out.** `POST /api/feedback` with no cookie returns `401` `{"error":"Sign in required."}`.

## Gotchas

- Thumbs are omitted while that reply is still streaming, on tool-only messages, and when no run id is available.
- The LangSmith key is read only by the auth server process. `launch.sh` sets `LANGSMITH_TRACING=false` on the LangGraph process. The auth process still needs `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` before a click is stored. A missing setting is not a passing feedback write.
- A real LangSmith row was not part of the skill's own proof run unless those variables were set and `list_feedback` showed the score.
