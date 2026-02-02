from __future__ import annotations

import argparse
import os
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings

from .config import load_config
from .storage import LocalJSONStore
from .workflow import build_workflow


UI_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Azure Underwriting UI</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }
      .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
      textarea { width: 100%; height: 220px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
      pre { background: #0b1020; color: #d8e1ff; padding: 12px; border-radius: 10px; overflow:auto; }
      button { padding: 10px 14px; border-radius: 10px; border: 1px solid #ccc; background: #fff; cursor: pointer; }
      button.primary { background: #2563eb; color: white; border-color: #2563eb; }
      select, input { padding: 8px; }
      .card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; margin-top: 14px; }
      .muted { color: #6b7280; }
    </style>
  </head>
  <body>
    <h2>Azure Mortgage Underwriting (LangGraph)</h2>
    <div class="muted">POST to <code>/api/submit</code> and view stored results at <code>/api/loan/&lt;case_id&gt;</code>.</div>

    <div class="card">
      <div class="row">
        <input id="file" type="file" />
        <select id="caseSelect"><option value="">(upload a file to choose a case)</option></select>
        <button id="loadCase">Load selected case</button>
        <button id="formatJson">Format JSON</button>
        <button id="openResult">Open result window</button>
        <button class="primary" id="submit">Submit</button>
      </div>
      <p class="muted">Accepts <code>{ "test_cases": [...] }</code> or a single case object.</p>
      <textarea id="json"></textarea>
    </div>

    <div class="card">
      <div class="row">
        <input id="caseId" placeholder="case_id to load (e.g. MTG-2025-001)" style="min-width: 340px;" />
        <button id="loadSaved">Load saved result</button>
      </div>
      <pre id="out">{}</pre>
    </div>

    <script>
      let uploaded = null;
      const $ = (id) => document.getElementById(id);

      function setOut(obj) {
        $("out").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2);
      }

      function extractCases(data) {
        if (Array.isArray(data)) return data;
        if (data && typeof data === "object" && Array.isArray(data.test_cases)) return data.test_cases;
        return null;
      }

      $("file").addEventListener("change", async (e) => {
        const f = e.target.files && e.target.files[0];
        if (!f) return;
        const text = await f.text();
        try {
          uploaded = JSON.parse(text);
        } catch (err) {
          uploaded = null;
          setOut("Invalid JSON file: " + err);
          return;
        }
        const cases = extractCases(uploaded);
        const sel = $("caseSelect");
        sel.innerHTML = '<option value="">(choose a case)</option>';
        if (!cases) {
          setOut("Uploaded JSON is not an array and doesn't contain test_cases[]");
          return;
        }
        cases.forEach((c, idx) => {
          const id = (c && c.case_id) ? c.case_id : ("case-" + (idx+1));
          const opt = document.createElement("option");
          opt.value = String(idx);
          opt.textContent = (idx+1) + ". " + id;
          sel.appendChild(opt);
        });
        setOut({ ok: true, cases: cases.length });
      });

      $("loadCase").addEventListener("click", () => {
        if (!uploaded) return setOut("Upload a test cases file first.");
        const cases = extractCases(uploaded);
        if (!cases) return setOut("No cases found in uploaded file.");
        const idx = parseInt($("caseSelect").value || "-1", 10);
        if (idx < 0 || idx >= cases.length) return setOut("Select a case first.");
        $("json").value = JSON.stringify(cases[idx], null, 2);
        $("caseId").value = cases[idx].case_id || "";
      });

      $("formatJson").addEventListener("click", () => {
        try {
          const obj = JSON.parse($("json").value || "{}");
          $("json").value = JSON.stringify(obj, null, 2);
        } catch (err) {
          setOut("Invalid JSON in textarea: " + err);
        }
      });

      $("submit").addEventListener("click", async () => {
        let obj;
        try {
          obj = JSON.parse($("json").value || "{}");
        } catch (err) {
          return setOut("Invalid JSON in textarea: " + err);
        }
        setOut({ status: "submitting..." });
        const resp = await fetch("/api/submit", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(obj) });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) return setOut({ error: "submit failed", status: resp.status, data });
        $("caseId").value = data.case_id || $("caseId").value;
        setOut(data);
        if (data.case_id) {
          window.open("/result/" + encodeURIComponent(data.case_id), "_blank");
        }
      });

      $("openResult").addEventListener("click", () => {
        const caseId = ($("caseId").value || "").trim();
        if (!caseId) return setOut("Enter a case_id first (or submit a case).");
        window.open("/result/" + encodeURIComponent(caseId), "_blank");
      });

      $("loadSaved").addEventListener("click", async () => {
        const caseId = ($("caseId").value || "").trim();
        if (!caseId) return setOut("Enter a case_id.");
        setOut({ status: "loading..." });
        const resp = await fetch("/api/loan/" + encodeURIComponent(caseId));
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) return setOut({ error: "load failed", status: resp.status, data });
        setOut(data);
      });
    </script>
  </body>
</html>
"""


RESULT_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Underwriting Result</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; }
      .row { display:flex; gap: 12px; flex-wrap: wrap; align-items: center; }
      .card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; margin-top: 14px; }
      button { padding: 10px 14px; border-radius: 10px; border: 1px solid #ccc; background: #fff; cursor: pointer; }
      pre { background: #0b1020; color: #d8e1ff; padding: 12px; border-radius: 10px; overflow:auto; white-space: pre-wrap; }
      .pill { display:inline-block; padding: 4px 10px; border-radius: 999px; background:#f3f4f6; }
      .ok { background:#dcfce7; }
      .warn { background:#fef9c3; }
      .bad { background:#fee2e2; }
      .muted { color:#6b7280; }
    </style>
  </head>
  <body>
    <h2>Loan approval result</h2>
    <div class="muted">This window loads the saved result from <code>/api/loan/&lt;case_id&gt;</code>.</div>

    <div class="card">
      <div class="row">
        <div>Case: <code id="case"></code></div>
        <div id="decisionPill" class="pill">loading...</div>
        <button id="refresh">Refresh</button>
      </div>
    </div>

    <div class="card">
      <div class="muted">Summary</div>
      <pre id="summary">{}</pre>
    </div>

    <div class="card">
      <div class="muted">Decision memo</div>
      <pre id="memo"></pre>
    </div>

    <script>
      const caseId = decodeURIComponent(location.pathname.split("/").pop() || "");
      document.getElementById("case").textContent = caseId;

      function setDecisionPill(decision) {
        const el = document.getElementById("decisionPill");
        el.className = "pill";
        if (decision === "APPROVED") el.classList.add("ok");
        else if (decision === "CONDITIONAL_APPROVAL") el.classList.add("warn");
        else if (decision === "DENIED") el.classList.add("bad");
        el.textContent = decision || "unknown";
      }

      async function load() {
        const resp = await fetch("/api/loan/" + encodeURIComponent(caseId));
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) {
          setDecisionPill("error");
          document.getElementById("summary").textContent = JSON.stringify({ error: "Not found", data }, null, 2);
          document.getElementById("memo").textContent = "";
          return;
        }

        setDecisionPill(data.final_decision);
        document.getElementById("summary").textContent = JSON.stringify({
          case_id: data.case_id,
          final_decision: data.final_decision,
          risk_score: data.risk_score,
          human_review_required: data.human_review_required,
          conditions: data.conditions,
          reasons: data.reasons
        }, null, 2);
        document.getElementById("memo").textContent = (data.decision_memo || "");
      }

      document.getElementById("refresh").addEventListener("click", load);
      load();
    </script>
  </body>
</html>
"""


SETUP_HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Azure Underwriting Setup</title>
    <style>
      body { font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; margin: 24px; max-width: 980px; }
      input { width: 100%; padding: 10px; border: 1px solid #d1d5db; border-radius: 10px; }
      label { display:block; margin-top: 12px; margin-bottom: 6px; font-weight: 600; }
      button { margin-top: 16px; padding: 10px 14px; border-radius: 10px; border: 1px solid #2563eb; background: #2563eb; color: white; cursor: pointer; }
      .muted { color: #6b7280; }
      .row { display:flex; gap: 12px; flex-wrap: wrap; }
      .card { border: 1px solid #e5e7eb; border-radius: 12px; padding: 14px; margin-top: 14px; }
      pre { background: #0b1020; color: #d8e1ff; padding: 12px; border-radius: 10px; overflow:auto; }
      code { background: #f3f4f6; padding: 2px 6px; border-radius: 8px; }
    </style>
  </head>
  <body>
    <h2>Configure Azure OpenAI</h2>
    <div class="muted">
      This server needs Azure OpenAI credentials to run the 5-agent underwriting workflow.
      Values are saved locally to <code>azure-underwriting-system/.env</code>.
    </div>

    <div class="card">
      <label>AZURE_OPENAI_ENDPOINT</label>
      <input id="endpoint" placeholder="https://YOUR-RESOURCE-NAME.openai.azure.com/" />

      <label>AZURE_OPENAI_API_KEY</label>
      <input id="key" placeholder="paste your key" />

      <div class="row">
        <div style="flex:1; min-width: 280px;">
          <label>AZURE_OPENAI_API_VERSION</label>
          <input id="version" placeholder="2024-10-21" value="2024-10-21" />
        </div>
        <div style="flex:1; min-width: 280px;">
          <label>UNDERWRITING_TEMPERATURE</label>
          <input id="temp" placeholder="1" value="1" />
        </div>
      </div>

      <label>AZURE_OPENAI_CHAT_DEPLOYMENT (your deployment name for gpt-5-mini)</label>
      <input id="chat" placeholder="gpt-5-mini" value="gpt-5-mini" />

      <label>AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT (recommended for RAG)</label>
      <input id="embed" placeholder="(optional) e.g. embeddings-deploy" value="" />

      <div class="row" style="margin-top: 16px;">
        <button id="save" style="margin-top:0;">Save</button>
        <button id="test" style="margin-top:0; background:#111827;border-color:#111827;">Test connection</button>
      </div>
    </div>

    <div class="card">
      <div class="muted">Status</div>
      <pre id="out">Loading...</pre>
      <div class="muted">After saving, go to <code>/ui</code> to submit cases.</div>
    </div>

    <script>
      const $ = (id) => document.getElementById(id);
      function setOut(obj) { $("out").textContent = typeof obj === "string" ? obj : JSON.stringify(obj, null, 2); }

      async function refresh() {
        const r = await fetch("/config");
        const j = await r.json().catch(() => ({}));
        setOut(j);
      }

      $("save").addEventListener("click", async () => {
        const payload = {
          AZURE_OPENAI_ENDPOINT: $("endpoint").value.trim(),
          AZURE_OPENAI_API_KEY: $("key").value.trim(),
          AZURE_OPENAI_API_VERSION: $("version").value.trim(),
          AZURE_OPENAI_CHAT_DEPLOYMENT: $("chat").value.trim(),
          AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT: $("embed").value.trim(),
          UNDERWRITING_TEMPERATURE: $("temp").value.trim(),
        };
        setOut({ status: "saving..." });
        const resp = await fetch("/setup", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
        const data = await resp.json().catch(() => ({}));
        setOut(data);
        await refresh();
      });

      $("test").addEventListener("click", async () => {
        setOut({ status: "testing..." });
        const resp = await fetch("/api/test/all");
        const data = await resp.json().catch(() => ({}));
        setOut(data);
        await refresh();
      });

      refresh();
    </script>
  </body>
</html>
"""


def _project_root_dir() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _write_env_file(values: Dict[str, str]) -> str:
    root = _project_root_dir()
    path = os.path.join(root, ".env")

    lines = []
    for k, v in values.items():
        if v is None:
            continue
        v = str(v)
        v = v.replace("\r", "").replace("\n", "")
        lines.append(f"{k}={v}")

    content = "\n".join(lines) + "\n"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _apply_env(values: Dict[str, str]) -> None:
    for k, v in values.items():
        if v is None:
            continue
        os.environ[str(k)] = str(v)


def _test_chat(cfg) -> Dict[str, Any]:
    llm = AzureChatOpenAI(
        azure_endpoint=cfg.azure_endpoint,
        api_version=cfg.api_version,
        api_key=cfg.api_key,
        azure_deployment=cfg.chat_deployment,
        temperature=1,
    )
    resp = llm.invoke(
        [
            SystemMessage(content="Return only the word OK."),
            HumanMessage(content="ping"),
        ]
    )
    return {"ok": True, "response_preview": str(resp.content or "")[:80]}


def _test_embeddings(cfg) -> Dict[str, Any]:
    if not cfg.embeddings_deployment:
        return {"ok": False, "skipped": True, "error": "No AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT set."}
    emb = AzureOpenAIEmbeddings(
        azure_endpoint=cfg.azure_endpoint,
        api_version=cfg.api_version,
        api_key=cfg.api_key,
        azure_deployment=cfg.embeddings_deployment,
    )
    vec = emb.embed_query("ping")
    return {"ok": True, "vector_length": len(vec)}


def _test_connection() -> Dict[str, Any]:
    try:
        cfg = load_config()
    except Exception as e:
        return {"ok": False, "error": str(e)}

    try:
        chat_res: Dict[str, Any] = _test_chat(cfg)
    except Exception as e:
        chat_res = {"ok": False, "error": str(e)}

    try:
        emb_res: Dict[str, Any] = _test_embeddings(cfg)
    except Exception as e:
        emb_res = {"ok": False, "error": str(e)}

    overall = bool(chat_res.get("ok"))
    return {
        "ok": overall,
        "chat_deployment": cfg.chat_deployment,
        "embeddings_deployment": cfg.embeddings_deployment,
        "chat": chat_res,
        "embeddings": emb_res,
        "note": "Embeddings are optional. If embeddings fail, the system uses keyword policy lookup.",
    }


def create_app(*, policies_pdf: str) -> FastAPI:
    store = LocalJSONStore(base_dir=os.path.join(_project_root_dir(), ".data"))

    app = FastAPI(title="Azure Underwriting Server", version="1.0")

    app.state.workflow = None
    app.state.ready = False
    app.state.config_error = "Not configured. Visit /setup."
    app.state.last_test = None
    app.state.policies_pdf = policies_pdf

    @app.get("/", response_class=JSONResponse)
    def root() -> Dict[str, Any]:
        return {
            "ok": True,
            "endpoints": {
                "setup": "/setup",
                "ui": "/ui",
                "result": "/result/{case_id}",
                "health": "/health",
                "config": "/config",
                "test": "/api/test/all",
                "submit": "POST /api/submit",
                "get_saved": "GET /api/loan/{case_id}",
            },
        }

    @app.get("/setup", response_class=HTMLResponse)
    def setup_page() -> str:
        return SETUP_HTML

    @app.post("/setup", response_class=JSONResponse)
    async def setup_save(request: Request) -> Dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object.")

        endpoint = str(body.get("AZURE_OPENAI_ENDPOINT") or "").strip()
        key = str(body.get("AZURE_OPENAI_API_KEY") or "").strip()
        version = str(body.get("AZURE_OPENAI_API_VERSION") or "2024-10-21").strip()
        chat = str(body.get("AZURE_OPENAI_CHAT_DEPLOYMENT") or "").strip()
        embed = str(body.get("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT") or "").strip()
        temp = str(body.get("UNDERWRITING_TEMPERATURE") or "1").strip()

        if not endpoint or not endpoint.lower().startswith("http"):
            raise HTTPException(status_code=400, detail="AZURE_OPENAI_ENDPOINT is required (must start with http).")
        if not key:
            raise HTTPException(status_code=400, detail="AZURE_OPENAI_API_KEY is required.")
        if not chat:
            raise HTTPException(status_code=400, detail="AZURE_OPENAI_CHAT_DEPLOYMENT is required.")

        values: Dict[str, str] = {
            "AZURE_OPENAI_API_KEY": key,
            "AZURE_OPENAI_ENDPOINT": endpoint,
            "AZURE_OPENAI_API_VERSION": version,
            "AZURE_OPENAI_CHAT_DEPLOYMENT": chat,
            "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT": embed,
            "UNDERWRITING_TEMPERATURE": temp,
        }

        env_path = _write_env_file(values)
        _apply_env(values)

        res = _test_connection()
        app.state.last_test = res
        app.state.ready = bool(res.get("ok"))
        app.state.workflow = None
        app.state.config_error = None if app.state.ready else str(
            res.get("error")
            or (res.get("chat") or {}).get("error")
            or (res.get("embeddings") or {}).get("error")
            or "Test failed"
        )

        return {
            "ok": app.state.ready,
            "saved_to": env_path,
            "configured": app.state.ready,
            "test": res,
            "error": app.state.config_error,
            "next": {"ui": "/ui", "health": "/health"},
        }

    @app.get("/ui", response_class=HTMLResponse)
    def ui() -> str:
        if not app.state.ready:
            return (
                "<html><body style='font-family: system-ui; margin: 24px;'>"
                "<h3>Server is not configured yet</h3>"
                "<p>Go to <a href='/setup'>/setup</a> to enter your Azure OpenAI endpoint and API key.</p>"
                f"<pre style='background:#0b1020;color:#d8e1ff;padding:12px;border-radius:10px;overflow:auto;'>"
                f"{(app.state.config_error or 'Missing configuration.')}</pre>"
                "</body></html>"
            )
        return UI_HTML

    @app.get("/result/{case_id}", response_class=HTMLResponse)
    def result_page(case_id: str) -> str:
        return RESULT_HTML

    @app.get("/health", response_class=JSONResponse)
    def health() -> Dict[str, Any]:
        return {"status": "ok", "configured": bool(app.state.ready), "error": app.state.config_error}

    @app.get("/config", response_class=JSONResponse)
    def config_status() -> Dict[str, Any]:
        return {
            "configured": bool(app.state.ready),
            "error": app.state.config_error,
            "last_test": app.state.last_test,
            "has_env_key": bool(os.getenv("AZURE_OPENAI_API_KEY")),
            "endpoint": os.getenv("AZURE_OPENAI_ENDPOINT", ""),
            "api_version": os.getenv("AZURE_OPENAI_API_VERSION", ""),
            "chat_deployment": os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", ""),
            "embeddings_deployment": os.getenv("AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", ""),
        }

    @app.get("/api/test/all", response_class=JSONResponse)
    def test_all() -> Dict[str, Any]:
        res = _test_connection()
        app.state.last_test = res
        app.state.ready = bool(res.get("ok"))
        app.state.config_error = None if app.state.ready else str(
            res.get("error")
            or (res.get("chat") or {}).get("error")
            or (res.get("embeddings") or {}).get("error")
            or "Test failed"
        )
        return res

    @app.post("/api/submit", response_class=JSONResponse)
    async def submit(request: Request) -> Dict[str, Any]:
        if not app.state.ready:
            raise HTTPException(status_code=503, detail=f"Server not configured or test failed. Visit /setup or /api/test/all. Error: {app.state.config_error}")

        if app.state.workflow is None:
            try:
                cfg = load_config()
                app.state.workflow = build_workflow(cfg=cfg, policies_pdf_path=app.state.policies_pdf)
            except Exception as e:
                app.state.workflow = None
                app.state.ready = False
                app.state.config_error = str(e)
                raise HTTPException(status_code=500, detail=f"Failed to build workflow: {e}")

        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object.")

        case_id = str(body.get("case_id") or "demo")
        result = app.state.workflow.run(case_id=case_id, applicant_data=body, thread_id=case_id)  # type: ignore[union-attr]
        store.save(case_id, result)

        return {
            "case_id": result.get("case_id"),
            "final_decision": result.get("final_decision"),
            "risk_score": result.get("risk_score"),
            "conditions": result.get("conditions", []),
            "reasons": result.get("reasons", []),
            "human_review_required": result.get("human_review_required", False),
            "decision_memo": result.get("decision_memo"),
        }

    @app.get("/api/loan/{case_id}", response_class=JSONResponse)
    def get_saved(case_id: str) -> Dict[str, Any]:
        data = store.get(case_id)
        if data is None:
            raise HTTPException(status_code=404, detail="Not found")
        return data

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run local underwriting API server (FastAPI).")
    parser.add_argument("--policies", required=True, help="Path to underwriting_policies.pdf")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    policies_pdf = os.path.abspath(args.policies)
    app = create_app(policies_pdf=policies_pdf)

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

