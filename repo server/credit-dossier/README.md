# Credit Dossier

Independent FastAPI app on port 8101, with GET /api/health, POST /api/run and /docs.

Open http://127.0.0.1:5174/#/repos/credit-dossier to review a credit memo. Upload PDF (selectable text), Word (.docx), UTF-8 text or Markdown, then ask questions about the document. The workspace displays extracted text and a question/answer review trail. Replacing or removing the memo clears previous answers.

POST /api/memo accepts a multipart `file` up to 5 MB and returns extracted text with page/paragraph labels (up to 100 PDF pages and 120,000 characters). No uploaded file is saved. Scanned PDFs require a text version or prior OCR. Word text includes table cells.

POST /api/run requires {"text":"Your question", "memo":"Extracted memo text", "provider":"gemini"} or provider "mistral". The prompt restricts answers to the memo, requests source citations, and instructs the model to acknowledge missing information. Review citations against the extracted document; model output is not independently fact-checked. Memo contents are held in browser memory and sent to the selected AI provider with each question; refresh clears the review. Uploading alone does not invoke AI or create runtime evidence.

The default route is the LiteLLM gateway (DOSSIER_ROUTE=gateway, GATEWAY_URL=http://127.0.0.1:4000), which records the app and a unique request ID. Provider keys for this route belong in `shadow server/backend/services/gateway/.env`. Its Gemini alias is gemini-3.5-flash-lite and Mistral alias is mistral-small.

For direct official Gemini/Mistral SDK use, select DOSSIER_ROUTE=sdk in this folder's .env and configure the corresponding key. Direct SDK calls do not create gateway clues. The React workspace includes a provider selector. See ../../README.md for live discovery behavior and shared launch commands.

Copy `.env.example` to `.env` in this folder. This server reads only its own .env; local values override inherited process variables. No common or sibling .env is used. Restart after changing settings.
