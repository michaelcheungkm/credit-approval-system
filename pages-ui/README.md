## Pages UI (Option B)

This directory contains a Cloudflare Pages UI for submitting mortgage/credit JSON test cases to your Worker and viewing results.

### Local dev

1. Start your Worker (in the repo root `credit-approval-system/`):

```powershell
npx wrangler dev --local --port 8787
```

2. Start Pages (in this folder):

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\pages-ui"
npx wrangler pages dev public --local --compatibility-date=2026-01-26
```

Wrangler will print a local Pages URL (often `http://localhost:8788`). Open it and use the UI.

### Deploy to Pages (production)

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\pages-ui"
npx wrangler pages project create credit-approval-ui
npx wrangler pages deploy public --project-name credit-approval-ui
```

In the Cloudflare dashboard for the Pages project, set environment variable:

- `WORKER_BASE_URL`: your deployed Worker URL, e.g. `https://credit-approval-system.<subdomain>.workers.dev`

