import { LoanState } from "./state/loan-state";
export { LoanState };

type Decision = "APPROVED" | "CONDITIONAL_APPROVAL" | "DENIED";

function asNumber(x: any): number | null {
  const n = typeof x === "number" ? x : typeof x === "string" ? Number(x) : NaN;
  return Number.isFinite(n) ? n : null;
}

function sumDebts(debts: any): number {
  if (!debts || typeof debts !== "object") return 0;
  // If total is provided, prefer it.
  const total = asNumber(debts.total_monthly_debt);
  if (total !== null) return total;
  return Object.entries(debts)
    .filter(([k, v]) => k !== "total_monthly_debt" && typeof v === "number")
    .reduce((acc, [, v]) => acc + (v as number), 0);
}

function computeDecision(input: any) {
  // Your mortgage_test_cases.json is "flat" (case_id at top-level, not nested applicant_data).
  const case_id = typeof input?.case_id === "string" ? input.case_id : "demo";

  const credit_score = asNumber(input?.credit_score) ?? 0;
  const monthly_income = asNumber(input?.employment?.monthly_income) ?? 0;

  const proposed_payment =
    asNumber(input?.loan?.monthly_piti) ??
    asNumber(input?.loan?.estimated_payment) ??
    0;

  // Prefer pre-calculated DTI if provided (matches the notebook's "do not recalculate" approach).
  // In your test cases, debts fields can represent balances or mixed semantics.
  const providedDtiRatio = asNumber(input?.dti_ratio);

  const existing_debt = sumDebts(input?.debts);
  const total_obligations = existing_debt + proposed_payment;

  const dti = (() => {
    if (providedDtiRatio !== null && providedDtiRatio >= 0 && providedDtiRatio <= 1.5) {
      return providedDtiRatio;
    }
    return monthly_income > 0 ? total_obligations / monthly_income : Number.POSITIVE_INFINITY;
  })();

  const loan_amount = asNumber(input?.loan?.amount) ?? 0;
  const appraised_value = asNumber(input?.property?.appraised_value) ?? 0;
  const ltv = appraised_value > 0 ? loan_amount / appraised_value : Number.POSITIVE_INFINITY;

  const liquid_assets_total =
    asNumber(input?.assets?.liquid_assets_total) ??
    ((asNumber(input?.assets?.checking) ?? 0) + (asNumber(input?.assets?.savings) ?? 0));

  const reserves_months =
    proposed_payment > 0 ? liquid_assets_total / proposed_payment : Number.POSITIVE_INFINITY;

  // Large deposits policy: > $1,000 OR > 25% monthly income (whichever is less) requires documentation.
  const depositThreshold = Math.min(1000, 0.25 * (monthly_income || 0));
  const recentDeposits = Array.isArray(input?.assets?.recent_deposits) ? input.assets.recent_deposits : [];
  const largeDeposits = recentDeposits
    .map((d: any) => ({ date: d?.date, amount: asNumber(d?.amount) ?? 0, description: d?.description }))
    .filter((d: any) => d.amount >= depositThreshold);

  const depositsDocumented =
    typeof input?.assets?.deposit_explanations === "string" &&
    input.assets.deposit_explanations.trim().length > 0;

  // Additional policy-related signals (used as conditions, not hard fails, for this baseline engine)
  const latePayments12mo = asNumber(input?.credit_history?.late_payments_12mo) ?? 0;
  const latePayments24mo = asNumber(input?.credit_history?.late_payments_24mo) ?? 0;
  const inquiries6mo = asNumber(input?.credit_history?.inquiries_6mo) ?? 0;
  const employmentYears = asNumber(input?.employment?.years) ?? asNumber(input?.employment?.years_employed) ?? 0;
  const employmentGap = String(input?.employment?.employment_gap ?? "").toLowerCase();
  const propertyType = String(input?.property?.type ?? input?.loan?.property_type ?? "");
  const requiredRepairs = asNumber(input?.property?.required_repairs) ?? 0;

  const conditions: string[] = [];
  const reasons: string[] = [];

  // Policy-driven decisioning (minimal deterministic baseline)
  // Credit score: conventional min 620 (from policy).
  if (credit_score < 620) {
    reasons.push(`Credit score ${credit_score} is below minimum 620.`);
  }

  // DTI policy: conventional max 43%; up to 50% only with compensating factors.
  if (!Number.isFinite(dti)) {
    reasons.push("DTI could not be calculated (missing/invalid income).");
  } else if (dti > 0.50) {
    reasons.push(`DTI ${(dti * 100).toFixed(1)}% is above 50%.`);
  }

  // LTV policy: allow up to 97% for primary residence; we treat >97% as excessive.
  if (!Number.isFinite(ltv)) {
    reasons.push("LTV could not be calculated (missing/invalid appraisal or loan amount).");
  } else if (ltv > 0.97) {
    reasons.push(`LTV ${(ltv * 100).toFixed(1)}% is above 97%.`);
  }

  // Reserves policy: at least 2 months for conventional primary; treat <2 as condition.
  if (!Number.isFinite(reserves_months)) {
    reasons.push("Reserves could not be calculated (missing/invalid payment or assets).");
  } else if (reserves_months < 2) {
    conditions.push(`Increase reserves to at least 2 months of PITI (currently ${reserves_months.toFixed(1)}).`);
  }

  // Late payments: policy says max 2 lates (30+ days) in last 12 months; LOE required for any lates in last 12 months.
  if (latePayments12mo > 0) {
    conditions.push(`Provide letter of explanation for ${latePayments12mo} late payment(s) in the last 12 months.`);
  }
  if (latePayments12mo > 2) {
    reasons.push(`Late payments in last 12 months (${latePayments12mo}) exceed maximum of 2.`);
  }
  // 60/90-day lates are not modeled in these test cases; if your data adds them, we can extend.

  // Employment: policy expects 2 years continuous history (same line/field). If <2 years in current job or gap reported, require documentation.
  if (employmentYears > 0 && employmentYears < 2) {
    conditions.push(`Employment tenure is ${employmentYears} years; provide full 2-year employment history and verification (VOE, W-2s, paystubs) and document continuity.`);
  }
  if (employmentGap === "yes") {
    conditions.push("Employment gap reported; provide letter of explanation and supporting documentation.");
  }

  // Collateral: if repairs required, require completion or escrow holdback per policy.
  if (requiredRepairs > 0) {
    const holdbackLimit = Math.min(5000, 0.03 * (appraised_value || 0));
    conditions.push(`Property repairs required ($${requiredRepairs.toLocaleString()}): complete prior to closing or establish escrow holdback (policy limit ~ $${Math.round(holdbackLimit).toLocaleString()}).`);
  }
  // Condo: require project review/documentation (policy section 4.6).
  if (propertyType.toLowerCase().includes("condo")) {
    conditions.push("Condominium: require project approval/review documentation (HOA budget, insurance, questionnaire, owner-occupancy, delinquencies, litigation).");
  }

  // Large deposits require sourcing documentation.
  if (largeDeposits.length > 0 && !depositsDocumented) {
    conditions.push(`Provide documentation/sourcing for ${largeDeposits.length} large deposit(s).`);
  }

  // Determine final decision
  let final_decision: Decision = "APPROVED";
  const hardFail = reasons.length > 0;
  if (hardFail) {
    final_decision = "DENIED";
  } else if (conditions.length > 0) {
    final_decision = "CONDITIONAL_APPROVAL";
  }

  // Simple risk score (0-100): higher is worse
  let risk_score = 0;
  risk_score += credit_score >= 740 ? 5 : credit_score >= 700 ? 15 : credit_score >= 660 ? 30 : credit_score >= 620 ? 45 : 70;
  risk_score += Number.isFinite(dti) ? Math.min(30, Math.max(0, (dti - 0.28) * 100)) : 30;
  risk_score += Number.isFinite(ltv) ? Math.min(25, Math.max(0, (ltv - 0.80) * 100)) : 25;
  risk_score += Number.isFinite(reserves_months) ? (reserves_months >= 6 ? 0 : reserves_months >= 2 ? 5 : 15) : 15;
  risk_score = Math.max(0, Math.min(100, Math.round(risk_score)));

  const decision_memo = [
    `### RISK_SCORE: ${risk_score}`,
    ``,
    `### DECISION: ${final_decision}`,
    ``,
    `### CREDIT_MEMO:`,
    ``,
    `**To:** Loan File ${case_id}`,
    `**From:** Underwriting Engine (Rules v0)`,
    `**Date:** ${new Date().toISOString().split("T")[0]}`,
    `**Subject:** Preliminary Underwriting Decision`,
    ``,
    `**Key Metrics:**`,
    `- Credit Score: ${credit_score}`,
    `- DTI: ${Number.isFinite(dti) ? (dti * 100).toFixed(1) + "%" : "N/A"}`,
    `- LTV: ${Number.isFinite(ltv) ? (ltv * 100).toFixed(1) + "%" : "N/A"}`,
    `- Reserves: ${Number.isFinite(reserves_months) ? reserves_months.toFixed(1) + " months" : "N/A"}`,
    ``,
    reasons.length ? `**Denial Reasons:**\n- ${reasons.join("\n- ")}` : `**Denial Reasons:**\n- None`,
    ``,
    conditions.length ? `**Conditions (if applicable):**\n- ${conditions.join("\n- ")}` : `**Conditions (if applicable):**\n- None`,
    ``,
  ].join("\n");

  return {
    case_id,
    final_decision,
    risk_score,
    metrics: {
      credit_score,
      monthly_income,
      existing_debt,
      proposed_payment,
      total_obligations,
      dti,
      loan_amount,
      appraised_value,
      ltv,
      liquid_assets_total,
      reserves_months,
      large_deposit_threshold: depositThreshold,
      large_deposits: largeDeposits,
    },
    conditions,
    reasons,
    decision_memo,
    raw_input: input,
    timestamp: new Date().toISOString(),
  };
}

const UI_HTML = `<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width,initial-scale=1" />
    <title>Credit Approval UI</title>
    <style>
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; max-width: 1100px; margin: 24px auto; padding: 0 16px; }
      textarea { width: 100%; min-height: 260px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; line-height: 1.4; }
      pre { background: #0b1020; color: #e7e9ee; padding: 12px; border-radius: 8px; overflow: auto; min-height: 260px; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
      button { padding: 10px 14px; margin-right: 8px; border-radius: 8px; border: 1px solid #d2d6e0; background: #f7f8fb; cursor: pointer; }
      button:hover { background: #eef1f7; }
      button:disabled { opacity: .6; cursor: not-allowed; }
      input[type="text"] { width: 360px; padding: 8px; }
      .muted { color: #666; font-size: 13px; }
      .bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
      .bar > * { margin: 4px 0; }
      code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    </style>
  </head>
  <body>
    <h2>Credit Approval (JSON)</h2>
    <p class="muted">
      This UI is served by the Worker itself. Endpoints: <code>/api/submit</code>, <code>/api/loan/&lt;case_id&gt;</code>, <code>/health</code>.
    </p>

    <div class="row">
      <div>
        <h3>Input</h3>
        <div class="bar">
          <input id="file" type="file" accept=".json,application/json" />
          <button id="loadFirst">Load first test case</button>
          <label class="muted">Pick:</label>
          <select id="caseSelect"></select>
          <button id="loadSelected">Load selected</button>
          <button id="prev">Prev</button>
          <button id="next">Next</button>
          <button id="format">Format JSON</button>
        </div>
        <p class="muted">
          Paste a single case JSON object (must include <code>case_id</code>).
          You can also upload a file or click “Load first test case” if your file contains an array of cases.
        </p>
        <textarea id="json" placeholder='{"case_id":"TEST-1","applicant_data":{...}}'></textarea>

        <div class="bar">
          <button id="submit">Submit</button>
          <button id="load">Load result by case_id</button>
          <input id="caseId" type="text" placeholder="case_id (e.g., TEST-1)" />
        </div>

        <p class="muted" id="status"></p>
      </div>

      <div>
        <h3>Result</h3>
        <pre id="result">{}</pre>
      </div>
    </div>

    <script>
      const $ = (id) => document.getElementById(id);
      const setStatus = (msg) => ($("status").textContent = msg);
      const pretty = (obj) => JSON.stringify(obj, null, 2);

      let loadedCases = [];

      function extractCases(v) {
        // Supported shapes:
        // - [ {case_id: ...}, ... ]
        // - { test_cases: [ {case_id: ...}, ... ] }
        // - { "<id>": {case_id: ...}, ... }
        if (Array.isArray(v)) return v;
        if (v && typeof v === "object" && Array.isArray(v.test_cases)) return v.test_cases;
        if (v && typeof v === "object") {
          const values = Object.values(v);
          const candidates = values.filter((x) => x && typeof x === "object" && "case_id" in x);
          if (candidates.length > 0) return candidates;
        }
        return [];
      }

      function populateSelect() {
        const sel = $("caseSelect");
        sel.innerHTML = "";
        loadedCases.forEach((c, idx) => {
          const opt = document.createElement("option");
          opt.value = String(idx);
          opt.textContent = (c && c.case_id)
            ? ((idx + 1) + ". " + c.case_id)
            : ((idx + 1) + ". (missing case_id)");
          sel.appendChild(opt);
        });
      }

      function loadCaseAt(index) {
        if (!loadedCases.length) {
          setStatus("No cases loaded yet. Upload mortgage_test_cases.json first.");
          return;
        }
        const idx = Math.max(0, Math.min(loadedCases.length - 1, index));
        const c = loadedCases[idx];
        $("json").value = pretty(c);
        $("caseId").value = c?.case_id || "";
        $("caseSelect").value = String(idx);
        const label =
          "Loaded case " +
          (idx + 1) +
          " of " +
          loadedCases.length +
          (c && c.case_id ? " (" + c.case_id + ")" : "") +
          ".";
        setStatus(label);
      }

      function safeJsonParse(text) {
        try { return { ok: true, value: JSON.parse(text) }; }
        catch (e) { return { ok: false, error: String(e) }; }
      }

      $("file").addEventListener("change", async (e) => {
        const f = e.target.files?.[0];
        if (!f) return;
        const text = await f.text();
        $("json").value = text;

        const parsed = safeJsonParse(text.trim());
        if (!parsed.ok) {
          loadedCases = [];
          populateSelect();
          setStatus(\`Loaded file: \${f.name} (but JSON is invalid: \${parsed.error})\`);
          return;
        }

        loadedCases = extractCases(parsed.value);
        populateSelect();
        setStatus(\`Loaded file: \${f.name} (\${loadedCases.length} case(s) detected).\`);
      });

      $("format").addEventListener("click", () => {
        const parsed = safeJsonParse($("json").value.trim());
        if (!parsed.ok) return setStatus(\`Invalid JSON: \${parsed.error}\`);
        $("json").value = pretty(parsed.value);
        setStatus("Formatted JSON.");
      });

      $("loadFirst").addEventListener("click", () => loadCaseAt(0));

      $("loadSelected").addEventListener("click", () => {
        const idx = Number($("caseSelect").value);
        if (!Number.isFinite(idx)) return;
        loadCaseAt(idx);
      });

      $("prev").addEventListener("click", () => {
        const idx = Number($("caseSelect").value || "0");
        loadCaseAt(idx - 1);
      });

      $("next").addEventListener("click", () => {
        const idx = Number($("caseSelect").value || "0");
        loadCaseAt(idx + 1);
      });

      $("submit").addEventListener("click", async () => {
        $("submit").disabled = true;
        try {
          setStatus("Submitting...");
          const raw = $("json").value.trim();
          const parsed = safeJsonParse(raw);
          if (!parsed.ok) throw new Error(\`Invalid JSON: \${parsed.error}\`);
          const body = parsed.value;
          if (!body || typeof body !== "object") throw new Error("JSON must be an object.");
          if (!body.case_id) throw new Error("JSON must include case_id.");
          $("caseId").value = body.case_id;

          const res = await fetch("/api/submit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          const text = await res.text();
          let out; try { out = JSON.parse(text); } catch { out = { raw: text }; }
          $("result").textContent = pretty(out);
          setStatus(res.ok ? "Submitted OK" : \`Submit failed (\${res.status})\`);
        } catch (err) {
          $("result").textContent = String(err);
          setStatus("Error");
        } finally {
          $("submit").disabled = false;
        }
      });

      $("load").addEventListener("click", async () => {
        $("load").disabled = true;
        try {
          setStatus("Loading...");
          const caseId = $("caseId").value.trim();
          if (!caseId) throw new Error("Enter case_id.");
          const res = await fetch(\`/api/loan/\${encodeURIComponent(caseId)}\`);
          const text = await res.text();
          let out; try { out = JSON.parse(text); } catch { out = { raw: text }; }
          $("result").textContent = pretty(out);
          if (out === null) {
            setStatus("No saved result for this case_id yet. Submit it first.");
          } else {
            setStatus(res.ok ? "Loaded OK" : \`Load failed (\${res.status})\`);
          }
        } catch (err) {
          $("result").textContent = String(err);
          setStatus("Error");
        } finally {
          $("load").disabled = false;
        }
      });
    </script>
  </body>
</html>`;

export default {
  async fetch(request: Request, env: any): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/") {
      return new Response(
        [
          "Credit Approval Worker is running.",
          "",
          "Try:",
          "- GET  /health",
          "- POST /api/submit",
          "- GET  /api/loan/<case_id>",
          "",
          "UI:",
          "- GET  /ui",
        ].join("\n"),
        { headers: { "Content-Type": "text/plain; charset=utf-8" } }
      );
    }

    if (url.pathname === "/ui") {
      return new Response(UI_HTML, {
        headers: { "Content-Type": "text/html; charset=utf-8" },
      });
    }

    if (url.pathname === "/health") return Response.json({ status: "ok" });

    if (url.pathname === "/api/submit" && request.method === "POST") {
      const body = await request.json();
      const result = computeDecision(body);

      const id = env.LOAN_STATE.idFromName(result.case_id);
      const stub = env.LOAN_STATE.get(id);
      await stub.fetch("http://do/save", { method: "POST", body: JSON.stringify(result) });

      return Response.json(result);
    }

    if (url.pathname.startsWith("/api/loan/") && request.method === "GET") {
      const caseId = url.pathname.split("/").pop() || "demo";
      const id = env.LOAN_STATE.idFromName(caseId);
      const stub = env.LOAN_STATE.get(id);
      return await stub.fetch("http://do/get");
    }

    return new Response("Not Found", { status: 404 });
  }
};
