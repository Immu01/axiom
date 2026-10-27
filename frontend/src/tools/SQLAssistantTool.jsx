import { useEffect, useState } from "react";
import { Database } from "lucide-react";
import ToolPanel from "./ToolPanel.jsx";
import { useToolStream } from "./useToolStream.js";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
const HISTORY_KEY = "axiom.sql.history.v1";

function loadHistory() {
  try {
    const history = JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
    return Array.isArray(history) ? history.slice(0, 8) : [];
  } catch {
    return [];
  }
}

function SQLReport({ result }) {
  return (
    <div className="sql-report">
      <h3>SQL (not executed)</h3>
      <pre className="tool-code-output"><code>{result.sql}</code></pre>
      <h3>Explanation in execution order</h3>
      <p>{result.explanation}</p>
      <h3>Clause breakdown</h3>
      <div className="sql-clause-list">
        {result.clause_breakdown.map((clause, index) => (
          <article className="tool-result-card" key={`${clause.token}-${index}`}>
            <code>{clause.token}</code><p>{clause.meaning}</p><small>{clause.role_in_this_query}</small>
          </article>
        ))}
      </div>
      <h3>Illustrative sample result</h3>
      <pre className="tool-code-output">{result.sample_result}</pre>
      <h3>Assumptions and safety</h3>
      <ul>{result.assumptions.map((item, index) => <li key={`a${index}`}>{item}</li>)}
        {result.safety_warnings.map((item, index) => <li className="tool-danger-text" key={`s${index}`}>{item}</li>)}</ul>
      <h3>Performance notes</h3>
      <ul>{result.performance_notes.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </div>
  );
}

export default function SQLAssistantTool({ apiKey }) {
  const stream = useToolStream({ apiUrl: API_URL, apiKey });
  const [question, setQuestion] = useState("");
  const [schema, setSchema] = useState("");
  const [sql, setSql] = useState("");
  const [dialect, setDialect] = useState("PostgreSQL");
  const [mode, setMode] = useState("generate");
  const [history, setHistory] = useState(loadHistory);

  useEffect(() => {
    try {
      localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 8)));
    } catch {
      /* Recent query history is optional when browser storage is unavailable. */
    }
  }, [history]);

  function submit(event) {
    event.preventDefault();
    if (mode === "generate" ? !question.trim() : !sql.trim()) return;
    setHistory((items) => [
      { question, schema, sql, dialect, mode, createdAt: Date.now() },
      ...items.filter((item) => item.question !== question || item.sql !== sql),
    ].slice(0, 8));
    stream.run("/api/tools/sql/assist", { question, schema, sql, dialect, mode });
  }

  function restore(item) {
    setQuestion(item.question || "");
    setSchema(item.schema || "");
    setSql(item.sql || "");
    setDialect(item.dialect || "PostgreSQL");
    setMode(item.mode || "generate");
  }

  return (
    <ToolPanel
      title="SQL Assistant"
      description="Generate SQL from plain English or explain a query. SQL is never run; sample results are illustrative."
      stream={stream}
      renderResult={(result) => <SQLReport result={result} />}
      fileName="axiom-sql-assistant"
    >
      <form onSubmit={submit}>
        <div className="tool-form-title"><Database size={18} /><h2>Describe or explain</h2></div>
        <div className="tool-mode-toggle" role="group" aria-label="SQL assistant mode">
          <button type="button" className={mode === "generate" ? "active" : ""} onClick={() => setMode("generate")}>Generate SQL</button>
          <button type="button" className={mode === "explain" ? "active" : ""} onClick={() => setMode("explain")}>Explain SQL</button>
        </div>
        {mode === "generate" ? (
          <>
            <label className="tool-label" htmlFor="sql-question">What should the query do?</label>
            <textarea id="sql-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="e.g. List monthly signups for the last year" rows={5} />
          </>
        ) : (
          <>
            <label className="tool-label" htmlFor="sql-query">SQL query</label>
            <textarea id="sql-query" className="tool-code-input" value={sql} onChange={(event) => setSql(event.target.value)} placeholder="Paste SQL to explain…" rows={8} spellCheck="false" />
          </>
        )}
        <label className="tool-label" htmlFor="sql-schema">Schema (optional)</label>
        <textarea id="sql-schema" className="tool-code-input" value={schema} onChange={(event) => setSchema(event.target.value)} placeholder="CREATE TABLE … or table / column list" rows={7} spellCheck="false" />
        <label className="tool-label" htmlFor="sql-dialect">Dialect</label>
        <select id="sql-dialect" value={dialect} onChange={(event) => setDialect(event.target.value)}>
          {["PostgreSQL", "MySQL", "SQLite", "SQL Server", "BigQuery", "Oracle"].map((item) => <option key={item}>{item}</option>)}
        </select>
        <button className="tool-submit" type="submit" disabled={stream.loading || (mode === "generate" ? !question.trim() : !sql.trim())}>Explain with Axiom</button>
      </form>
      {history.length > 0 && <div className="sql-history">
        <h3>Recent queries</h3>
        {history.map((item, index) => (
          <button type="button" key={`${item.createdAt}-${index}`} onClick={() => restore(item)}>
            <span>{item.mode === "explain" ? item.sql : item.question}</span>
            <small>{item.dialect}</small>
          </button>
        ))}
      </div>}
    </ToolPanel>
  );
}
