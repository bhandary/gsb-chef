# API keys in the gear menu

A signed-in user opens the gear, types an OpenAI key and a Tavily key, and saves them in this browser. Later chat requests from this browser send those keys. The account database does not store them.

## Sub-features

- `open-gear` shows the Recipe API keys form.
- `save-keys` keeps both values in `localStorage` for the LangGraph origin.
- `blank-field` clears a saved value so the agent falls back to the environment variable.
- `cancel` closes the form without writing.

## How to get to it (user POV)

- Reach the chat by verifying an email or signing in.
- Choose the gear button in the header, labeled API key settings.
- Type into OpenAI API key and Tavily API key, then choose Save or Cancel.

## Driving it with Playwright

Preconditions:

- `DOCTOR OK` and a verified session.
- Use a fresh browser context. Do not type a real key. A proof of the form uses obvious stand-in strings and must not send a chat afterward.
- If the goal is a successful recipe, this feature is the wrong journey. Use `chef-chat.md`, and only when real keys are already available.

- **Open.** Click the button `API key settings`. The heading `Recipe API keys` is visible, with labels `OpenAI API key` and `Tavily API key`.
- **Cancel.** Fill `sk-cancel-not-used` into OpenAI API key, click `Cancel`, and open the gear again. That field is empty.
- **Save.** Fill `sk-local-proof-0000` into OpenAI API key and `tvly-local-proof-0000` into Tavily API key. Click `Save`. The heading is gone.
- **Read this browser.** `localStorage["gsb:chat:openaiApiKey"]` is `sk-local-proof-0000`, `localStorage["gsb:chat:tavilyApiKey"]` is `tvly-local-proof-0000`, and `localStorage["gsb:chat:providerKeyHost"]` is `http://localhost:2024`.
- **Leave the database alone.** Query the launch `GSB_AUTH_DB`. Neither stand-in string appears in the file.
- **Clear.** Open the gear, clear both fields, click `Save`. Both `localStorage` key values are empty strings.

## Gotchas

- The gear control is a button, not a link. The form is not a `dialog` element. Match the heading `Recipe API keys`.
- Saved keys are scoped to the LangGraph origin in `NEXT_PUBLIC_API_URL`, which is `http://localhost:2024`, not the page origin `http://127.0.0.1:3000`.
- Saving a stand-in and then sending a chat proves the missing or rejected key path, not this form. Clear the fields before any chef-chat attempt in the same context.
- The server is not supposed to write these values into `data/auth.db` or into `.langgraph_api`. The check is the absence of the stand-in string in the launch database. Do not grep a real key into a log.
