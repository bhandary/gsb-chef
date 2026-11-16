# Chat with the chef

A signed-in user lists leftover ingredients, sends them, and reads a recipe suggestion from the agent.

## Sub-features

- `composer` shows the ingredient box and Send after a verified session. The empty box is about four lines tall (`min-h-28` on the textarea in `web/src/components/thread/index.tsx`).
- `send-ingredients` submits the text the user typed.
- `recipe-reply` shows the agent's recipe text in the thread. The system prompt in `gsb_chef.py` limits those suggestions to Gaud Saraswat Brahmin (GSB) Konkani cuisine.

## How to get to it (user POV)

- Sign up and open the verification link, or sign in, so the chat replaces the account form.
- Type leftover ingredients into the box whose placeholder is `List leftover ingredients, for example rice, coconut, and curry leaves`.
- Choose Send.

## Driving it with Playwright

Preconditions:

- `DOCTOR OK`, and a verified session in this browser context (`signup-and-verification.md` or `login-and-session.md`).
- Both an OpenAI key and a Tavily key are available, either as non-empty `OPENAI_API_KEY` and `TAVILY_API_KEY` in the environment the langgraph process loaded, or as values the user already saved in the gear menu for `http://localhost:2024`.
- If either key is missing, stop. Report which one is absent. Do not invent a key, do not ask for a real key, and do not call this feature verified because the missing-key toast appeared.

- **Focus the composer.** Wait for the placeholder `List leftover ingredients, for example rice, coconut, and curry leaves`. The empty textarea includes `min-h-28`. At a 16px root font size its client height is 112px, about four lines.
- **Enter ingredients.** Fill that textbox with `rice, coconut, and curry leaves`. The button `Send` becomes enabled.
- **Send.** Click `Send`. The button label becomes `Cancel` while the run is in progress.
- **Read the reply.** Wait until `Cancel` is gone and the thread contains a reply that is not the user's ingredient line. Screenshot the thread into the run's `evidence/chef-reply.png`.
- **Record the failure if the provider rejects the key.** A toast titled `An error occurred. Please try again.` whose description names `OpenAI request failed` or `Tavily search failed` means the request was sent and the provider refused it. Save the toast text. That is not a recipe proof.

## Gotchas

- Send stays disabled while the textbox is empty.
- Enter in the textbox submits the form. Shift+Enter does not.
- The assistant id the UI sends is `agent`. Doctor already required that graph on port 2024.
- Keys typed into the gear menu override the environment. A leftover fake key in `localStorage` makes this journey use the fake key. Check `gsb:chat:openaiApiKey` and `gsb:chat:tavilyApiKey` before sending. `gsb:chat:providerKeyHost` must be `http://localhost:2024` or the UI ignores the stored keys.
- No recipe was verified by the skill's own proof run when those environment variables were empty. The sign-up proof does not cover this feature.
