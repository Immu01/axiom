import { useState } from "react";
import { Code } from "lucide-react";
import ToolPanel from "./ToolPanel.jsx";
import { useToolStream } from "./useToolStream.js";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

function CodeReport({ result, original }) {
  const [issueFilter, setIssueFilter] = useState("all");
  const [selectedLines, setSelectedLines] = useState([]);
  const issues = issueFilter === "all"
    ? result.issues
    : result.issues.filter((issue) => issue.severity === issueFilter);

  return (
    <div className="code-review-result">
      <h3>{result.language_detected}</h3>
      <p>{result.purpose_summary}</p>
      {result.issues.length > 0 ? (
        <>
          <h3>Findings</h3>
          <div className="issue-filters" role="group" aria-label="Filter issues by severity">
            {["all", "critical", "high", "medium", "low", "info"].map((severity) => (
              <button
                key={severity}
                type="button"
                className={issueFilter === severity ? "active" : ""}
                aria-pressed={issueFilter === severity}
                onClick={() => setIssueFilter(severity)}
              >
                {severity}
              </button>
            ))}
          </div>
          {issues.map((issue, index) => (
            <article className="tool-result-card" key={`${issue.title}-${index}`}>
              <span className={`severity-badge ${issue.severity}`}>{issue.severity}</span>
              <b>{issue.title}</b>
              <span>Lines: {issue.line_refs.join(", ") || "not specified"}</span>
              <p>{issue.explanation}</p>
              <small>Suggested fix: {issue.suggested_fix}</small>
            </article>
          ))}
        </>
      ) : <p className="tool-status">No specific issues found in this review.</p>}
      <h3>Line-by-line explanation</h3>
      {result.line_by_line.map((line, index) => (
        <button
          className={`tool-result-card line-explanation ${selectedLines.includes(line.start_line) ? "selected" : ""}`}
          key={`${line.start_line}-${index}`}
          type="button"
          aria-pressed={selectedLines.includes(line.start_line)}
          onClick={() => setSelectedLines(Array.from({ length: line.end_line - line.start_line + 1 }, (_, offset) => line.start_line + offset))}
        >
          <span>Lines {line.start_line}{line.end_line !== line.start_line ? `–${line.end_line}` : ""}</span>
          <pre>{line.code}</pre>
          <p>{line.explanation}</p>
        </button>
      ))}
      {selectedLines.length > 0 && (
        <>
          <h3>Selected source lines</h3>
          <pre className="tool-source-view">{original.split("\n").map((line, index) => (
            <span className={selectedLines.includes(index + 1) ? "selected" : ""} key={index}>
              <i>{index + 1}</i>{line || " "}
            </span>
          ))}</pre>
        </>
      )}
      <h3>Execution flow</h3>
      <ol>{result.execution_flow.map((step, index) => <li key={index}>{step}</li>)}</ol>
      <h3>Complexity</h3>
      <p>{result.complexity}</p>
      <h3>Improved version</h3>
      <div className="code-diff-grid">
        <div><h4>Original</h4><pre className="tool-code-output">{original}</pre></div>
        <div><h4>Suggested</h4><pre className="tool-code-output">{result.improved_code || "No refactor suggested."}</pre></div>
      </div>
      <h3>Tests to consider</h3>
      <ul>{result.test_suggestions.map((item, index) => <li key={index}>{item}</li>)}</ul>
    </div>
  );
}

export default function CodeReviewTool({ apiKey }) {
  const stream = useToolStream({ apiUrl: API_URL, apiKey });
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("");
  const [focus, setFocus] = useState("all");

  function submit(event) {
    event.preventDefault();
    if (!code.trim()) return;
    stream.run("/api/tools/code-review/analyze", { code, language, focus });
  }

  return (
    <ToolPanel
      title="Code Review"
      description="Understand control flow, identify likely issues, and get a safe refactor suggestion. Code is never executed."
      stream={stream}
      renderResult={(result) => <CodeReport result={result} original={code} />}
      fileName="axiom-code-review"
    >
      <form onSubmit={submit}>
        <div className="tool-form-title"><Code size={18} /><h2>Code to review</h2></div>
        <label className="tool-label" htmlFor="review-code">Source code</label>
        <textarea id="review-code" className="tool-code-input" value={code} onChange={(event) => setCode(event.target.value)} placeholder="Paste code here…" rows={18} spellCheck="false" />
        <div className="tool-field-grid">
          <label className="tool-label">Language<input value={language} onChange={(event) => setLanguage(event.target.value)} placeholder="Auto-detect" /></label>
          <label className="tool-label">Focus
            <select value={focus} onChange={(event) => setFocus(event.target.value)}>
              <option value="all">All areas</option>
              <option value="bugs">Bugs</option>
              <option value="security">Security</option>
              <option value="performance">Performance</option>
              <option value="readability">Readability</option>
            </select>
          </label>
        </div>
        <button className="tool-submit" type="submit" disabled={stream.loading || !code.trim()}>Review code</button>
      </form>
    </ToolPanel>
  );
}
