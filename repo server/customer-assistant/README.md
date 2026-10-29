# Customer Assistant (scenario 6)

A conversation chatbot using the official Gemini, Mistral and OpenAI SDKs.
Open http://127.0.0.1:5174/#/repos/customer-assistant. The backend uses port 8105.

Copy `.env.example` to `.env` in this folder and configure GEMINI_API_KEY (or
GOOGLE_API_KEY), GEMINI_MODEL, MISTRAL_API_KEY, MISTRAL_MODEL, OPENAI_API_KEY and
OPENAI_MODEL as needed. This server never reads shared or sibling .env files.
Local settings override process variables, including explicitly empty keys.
Restart the server after changing settings.

Conversation history stays in the browser for the current session and is cleared
when switching providers. Only invocation metadata is recorded in sdk_calls.jsonl
for discovery; prompts, replies and API keys are excluded.

## Deliberately fake credential for discovery testing

The following credential is a nonfunctional demo value. The chatbot never reads it.
It exists only so repository secret scanning can detect an exposed key in a README.

```text
OPENAI_API_KEY=sk-proj-DEMO_CUSTOMER_ASSISTANT_NOT_A_REAL_KEY_0123456789abcdef
```
