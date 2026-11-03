# Missing-key error

A signed-in user sends ingredients without an OpenAI key and sees an error that tells them to enter one in chat settings or set `OPENAI_API_KEY`. This is the failure path, not a recipe.

## Sub-features

- `send-without-keys` submits the composer when neither the browser nor the agent environment has a key.
- `missing-openai-toast` shows the missing `OPENAI_API_KEY` text.

## How to get to it (user POV)

- Sign in, or finish email verification, and land on the chat.
- Leave the gear menu empty.
- Type ingredients and choose Send.

## Driving it with Playwright

Preconditions:

- `DOCTOR OK` and a verified session in a fresh browser context, so `localStorage` has no `gsb:chat:openaiApiKey` and no `gsb:chat:tavilyApiKey`.
- The langgraph process has an empty `OPENAI_API_KEY` and an empty `TAVILY_API_KEY`. Confirm without printing the values: if either variable is non-empty in that process environment, stop and report that a key is present. Do not unset a real key to force this error.
- The launch script does not export either key. A root `.env` that contains one is still loaded by `langgraph dev` and counts as present.

- **Send.** Wait for the ingredient placeholder. Fill `rice and coconut`. Click `Send`.
- **Read the toast.** A toast titled `An error occurred. Please try again.` appears, and its description contains `OPENAI_API_KEY is missing. Enter it in the chat settings or set OPENAI_API_KEY in the environment.`
- **Save the text.** Write the toast description into the run's `evidence/missing-key-toast.txt` and screenshot `evidence/missing-key-toast.png`.
- **Stop there.** Do not fill the gear menu with a made-up key and send again in order to get a different error.

## Gotchas

- A toast that says `using the request API key ending in` or `using the environment API key ending in` means a key was present. That is not this feature. Report the source word and the last four characters only.
- Tavily is not consulted when the OpenAI key is already missing. Do not expect a Tavily message on this path.
- The composer error is a toast, not the red account-form paragraph.
- This path does not verify that the chef can produce a recipe.
