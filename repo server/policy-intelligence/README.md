# Policy Intelligence (Scenario 2)

Open http://127.0.0.1:5174/#/repos/policy-intelligence. This independent FastAPI service runs on port 8102 and replaces Loan Ops Helper. Old frontend bookmarks redirect to the new workspace.

Enter company details, industry, purpose, operating history, principal, tenure, annual revenue and cash flow, existing annual repayments, collateral, company credit score, defaults, KYC status and audited financial statement availability. All amounts are INR. Compliant and violating examples are included in the form.

`bank_policy.json` is the fictional bank policy document and the single source of clause thresholds. The workspace renders the same document and offers a download. The agent loads it, calculates payment and coverage ratios, and returns every clause with its actual value and pass/violation status. The illustrative fixed interest rate is 12%. Debt service uses annualised equal monthly instalments; fees are excluded. Comparisons use unrounded values. A policy pass is not a lending approval.

Checks work without a provider key. Select **Add an AI agent explanation**, then choose **OpenAI**, **Mistral** or **Gemini** in the form. The selected provider's official Python SDK receives the form, policy and authoritative assessment. AI failure leaves clause findings available and is explicitly reported. Credentials stay on the server.

| Provider | SDK package | API key | Optional model setting | Default model |
| --- | --- | --- | --- | --- |
| OpenAI | openai | OPENAI_API_KEY | OPENAI_MODEL | gpt-4o-mini |
| Mistral | mistralai | MISTRAL_API_KEY | MISTRAL_MODEL | mistral-small-latest |
| Gemini | google-genai | GEMINI_API_KEY or GOOGLE_API_KEY | GEMINI_MODEL | gemini-2.5-flash |

Copy `.env.example` to `.env` in this folder. This server reads only its own `.env`; local values override inherited process variables, including explicitly blank keys. Restart after configuration changes. Install this repository's requirements when using a separate Python environment. `/api/policy` reports provider availability and model names without exposing keys.

Actual SDK attempts write metadata only to `shadow server/backend/logs/sdk_calls.jsonl`: request ID, app, provider, model, timestamp and success/failure. They do not log company data, policy content, explanations or keys. Run discovery after requesting an AI explanation to collect S2 runtime evidence. Local checks do not fabricate AI usage. Existing Git history is preserved for historical secret discovery.

API: `GET /api/health`, `GET /api/policy`, `GET /api/policy/download`, `POST /api/run` (`loan` object plus optional `ai_explanation` boolean and `provider` (`openai`, `mistral` or `gemini`; default `openai`)). See `/docs` for the schema.


SDK references: [OpenAI official API documentation](https://developers.openai.com/api/reference/python/resources/chat/subresources/completions/methods/create), [Mistral SDK documentation](https://docs.mistral.ai/resources/sdks), [Gemini text generation](https://ai.google.dev/gemini-api/docs/text-generation).
