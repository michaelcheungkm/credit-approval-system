# Credit Approval System (Cloudflare Worker + UI)

This project is a Cloudflare Workers-based mortgage/credit underwriting prototype.

It accepts a JSON “case”, computes a **policy-inspired underwriting decision** (rules-based baseline), stores the result in a **Durable Object**, and provides a simple **web UI** for uploading/selecting test cases and viewing results.

## What’s included

- **Worker API + built-in UI** (`src/index.ts`)
  - `GET /` – helpful landing text
  - `GET /ui` – browser UI (upload/paste JSON, pick a test case, submit, load saved result)
  - `GET /health` – health check
  - `POST /api/submit` – compute decision + save to Durable Object
  - `GET /api/loan/<case_id>` – fetch saved result for that case id
- **Durable Object** (`src/state/loan-state.ts`)
  - Stores the latest computed decision/result for each `case_id`
- **Pages UI (optional)** (`pages-ui/`)
  - Static UI + Pages Functions proxy to forward `/api/*` calls to the Worker (useful for deployment)

## Local development

### 1) Install deps

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system"
npm install
```

### 2) Run the Worker (local mode)

```powershell
npx wrangler dev --local --port 8787
```

Open:
- `http://localhost:8787/ui`
- `http://localhost:8787/health`

### 3) Use the provided test cases

Your test cases file is:
`C:\Users\user\SynologyDrive\Simon\Credit Project\mortgage_test_cases.json`

It has the shape:

```json
{ "test_cases": [ ... ] }
```

In the UI:
1. Upload the file
2. Use the dropdown to pick Case 1 / 2 / 3…
3. Click **Submit**
4. Use **Load result by case_id** to fetch the stored decision later

## Decision output (what you’ll see)

`POST /api/submit` returns a JSON result with fields like:
- `case_id`
- `final_decision`: `APPROVED` | `CONDITIONAL_APPROVAL` | `DENIED`
- `risk_score` (0–100; higher is worse)
- `metrics` (DTI, LTV, reserves, etc.)
- `conditions` (for conditional approvals)
- `reasons` (for denials)
- `decision_memo` (human-readable memo)

## Optional: run the Pages UI locally

Note: Wrangler Pages dev may try to start in remote mode; if prompted, switch to local mode.

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\pages-ui"
npx wrangler pages dev public
```

The Pages proxy uses `WORKER_BASE_URL` (defaults to `http://localhost:8787` in local dev).

## Deploy

### Deploy the Worker

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system"
npx wrangler deploy
```

### Deploy the Pages UI (optional)

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\pages-ui"
npx wrangler pages project create credit-approval-ui
npx wrangler pages deploy public --project-name credit-approval-ui
```

Then set Pages environment variable:
- `WORKER_BASE_URL` = your Worker URL (e.g. `https://<worker>.workers.dev`)

## Notes / next upgrades

- The current decision engine is a **deterministic rules baseline**.
- The repo already includes LangGraph/LangChain deps; next steps could integrate:
  - Workers AI (Llama 3.3) or Azure OpenAI
  - Policy retrieval (RAG) from `underwriting_policies.pdf`
  - Multi-agent workflow (Credit/Income/Asset/Collateral/Critic/Decision) using LangGraph

