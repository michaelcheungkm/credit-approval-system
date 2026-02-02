## Azure Mortgage Underwriting (LangGraph, multi-agent)

This folder contains a **Python** implementation of the Senior Mortgage Underwriting multi-agent workflow using:

- **LangGraph** for orchestration (Supervisor → specialist agents → Decision)
- **Azure OpenAI** for the LLM (`gpt-5-mini` via your Azure deployment)
- **RAG over** `underwriting_policies.pdf`
  - Uses **Chroma** if an embeddings deployment is configured
  - Otherwise falls back to **keyword policy lookup** (still works)
- **PII sanitization** + simple **bias-signal flagging**
- A **local server UI** to submit cases and view results
- A CLI to run the provided test cases in `mortgage_test_cases.json`

### What it does

For each loan application (case), the workflow produces:

- `credit_analysis`
- `income_analysis`
- `asset_analysis`
- `collateral_analysis`
- `decision_memo`
- `final_decision` (`APPROVED` | `CONDITIONAL_APPROVAL` | `DENIED`)
- `risk_score` (0–100; higher = worse)
- `conditions` / `reasons`
- `reasoning_chain` (audit trail)

### Prerequisites

- Python 3.10+ recommended
- Your Azure OpenAI resource + **deployments**:
  - Chat deployment: model **gpt-5-mini**
  - Embeddings deployment (optional): e.g. **text-embedding-3-large** (or whatever you deployed)

### Setup

Create a venv and install dependencies:

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\azure-underwriting-system"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

You can configure Azure credentials in either way:

- **Option A (recommended)**: use the web setup page (no manual `.env` editing)
- **Option B**: create a `.env` file (copy from `.env.example`) and fill in your Azure values

---

## Start the local server (UI + API)

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\azure-underwriting-system"
.\.venv\Scripts\Activate.ps1
python -m underwriting_system.server --policies "..\..\underwriting_policies.pdf" --host 127.0.0.1 --port 8010
```

Open:

- **Setup (enter Azure key/endpoint + test connection)**: `http://127.0.0.1:8010/setup`
- **Main UI (submit cases)**: `http://127.0.0.1:8010/ui`
- **Health**: `http://127.0.0.1:8010/health`

### Separate result window

When you submit a case in `/ui`, it automatically opens a separate result window:

- `http://127.0.0.1:8010/result/<case_id>`

Example:

- `http://127.0.0.1:8010/result/MTG-2025-001`

The result page reads the saved result from:

- `GET /api/loan/<case_id>`

---

## API endpoints

- `GET /health`: server status + whether Azure chat is configured
- `GET /config`: current config status (no secrets returned)
- `GET /api/test/all`: test chat + (optional) embeddings connectivity
- `POST /api/submit`: run the 5-agent workflow on a JSON case and save the result
- `GET /api/loan/<case_id>`: retrieve the saved full result (including memo)

### Run all test cases

```powershell
cd "c:\Users\user\SynologyDrive\Simon\Credit Project\credit-approval-system\azure-underwriting-system"
.\.venv\Scripts\Activate.ps1
python -m underwriting_system.run_cases ^
  --policies "..\..\underwriting_policies.pdf" ^
  --testcases "..\..\mortgage_test_cases.json"
```

### Notes

- The workflow uses the **provided `dti_ratio`** in `mortgage_test_cases.json` as the authoritative DTI (and will only compute DTI if missing).
- Decisioning is **guardrailed** with a deterministic baseline score/decision so you get stable outputs across runs, while the LLM produces the audit memo and per-domain narrative.
- If embeddings fail (e.g. `DeploymentNotFound`), the system still runs using **keyword policy lookup**.

