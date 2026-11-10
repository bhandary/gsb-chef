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

- `DOCTOR OK`, and a verified session in this browser context. `drive-signup.sh` on this launch creates that session.
- This feature does not require an OpenAI or Tavily key. A state update alone does not attach a run id, and thumbs stay hidden without one.
- Do not put `LANGSMITH_API_KEY` into the page, a screenshot, or a log.

From the repo root, after sign-up:

```bash
bash .cursor/skills/verify-gsb-chef/scripts/drive-feedback.sh
```

The script signs in, seeds the thread, and writes the evidence below. The seed steps, if you drive them yourself, are:

- **Create the thread.** `POST http://127.0.0.1:2024/threads` with `metadata.graph_id` set to `agent`. Without that field, `POST /threads/{id}/state` returns 400 because the thread has no graph.
- **Post the reply.** `POST /threads/{id}/state` with a human message and an assistant message whose content is text. That checkpoint has `metadata.source` `update` and no `run_id`.
- **Stamp a run id.** `POST /threads/{id}/runs/wait` with `assistant_id` `agent` and one more human message. The run may fail with the missing `OPENAI_API_KEY` error. The input checkpoint still contains the seeded assistant message, and its `metadata.run_id` is a UUID. That UUID is the `trace_id` the UI sends.
- **Open the thread.** Go to `/?threadId=<id>` and wait for the assistant text.
- **See both thumbs.** Wait for the buttons `Thumbs up` and `Thumbs down`. Neither has `aria-pressed="true"`. Screenshot that state.
- **Click one.** Click `Thumbs up`. Read the `POST /api/feedback` request body and the response status and body.
- **Selected state.** When the response is `200` and `logged` is true, the button stays pressed. Screenshot it. When the response is `feedback not configured`, the button returns to unpressed and a toast says `Could not save feedback`. To screenshot the pressed style without a LangSmith key, fulfill a later `/api/feedback` response as `200` `{"ok":true,"logged":true}` and click again.
- **Clear.** Click the same thumb again. No further `/api/feedback` request is sent, and `aria-pressed` is false.
- **Signed out.** `POST /api/feedback` with no cookie returns `401` `{"error":"Sign in required."}`.

## Gotchas

- Thumbs are omitted while that reply is still streaming, on tool-only messages, and when no run id is available. The state-update checkpoint is one of those cases: `metadata.run_id` is empty until a run writes a later checkpoint that still contains the message.
- Playwright's `request.headers()` omits the `Cookie` header. A `503` `feedback not configured` from `POST /api/feedback`, rather than `401` `Sign in required.`, is the check that the `gsb_session` cookie was sent. `request.allHeaders()` includes the cookie name.
- The LangSmith key is read only by the auth server process. `launch.sh` sets `LANGSMITH_TRACING=false` on the LangGraph process. The auth process still needs `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` before a click is stored. A missing setting is not a passing feedback write.
- The agent server and the auth server must use the same `LANGSMITH_PROJECT`. When it is unset, both use the SDK default project name, `default`. The auth server looks that project up once and sends its id as `session_id`. A failed lookup still sends the feedback without a project id.
- A real LangSmith row was not part of the skill's own proof run unless those variables were set and `list_feedback` showed the score.
