import { useState } from "react";
import { Check, Copy, Download, Sparkles, Square } from "lucide-react";

function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function markdownValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => {
      if (item && typeof item === "object") {
        return `- ${Object.entries(item).map(([key, nested]) => `**${key.replaceAll("_", " ")}:** ${markdownValue(nested)}`).join(" · ")}`;
      }
      return `- ${String(item)}`;
    }).join("\n");
  }
  if (value && typeof value === "object") {
    return Object.entries(value)
      .map(([key, nested]) => `**${key.replaceAll("_", " ")}:** ${markdownValue(nested)}`)
      .join("\n\n");
  }
  return String(value ?? "");
}

function toMarkdown(value) {
  if (!value) return "";
  if (typeof value.markdown === "string") return value.markdown;
  return Object.entries(value)
    .filter(([key]) => key !== "truncated")
    .map(([key, item]) => `## ${key.replaceAll("_", " ")}\n\n${markdownValue(item)}`)
    .join("\n\n");
}

export default function ToolPanel({ title, description, stream, children, renderResult, fileName }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState("");
  const structured = stream.result?.data || null;
  const markdown = toMarkdown(structured || stream.result);
  const visibleMarkdown = markdown || stream.raw;

  async function copyResult() {
    try {
      await navigator.clipboard.writeText(visibleMarkdown);
      setCopied(true);
      setCopyError("");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setCopied(false);
      setCopyError("Could not copy the result. Check clipboard permissions and try again.");
    }
  }

  return (
    <main className="tool-workspace">
      <header className="tool-heading">
        <div>
          <p className="tool-eyebrow">Axiom tools</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {stream.provider && <span className="tool-provider">{stream.provider}</span>}
      </header>
      <div className="tool-content">
        <section className="tool-form-card">{children}</section>
        <section className="tool-output-card" aria-live="polite" aria-busy={stream.loading}>
          <div className="tool-output-header">
            <h2>Result</h2>
            {(structured || stream.result?.markdown) && (
              <div className="tool-output-actions">
                <button className="tool-action" onClick={copyResult} aria-label="Copy result">
                  {copied ? <Check size={15} /> : <Copy size={15} />}
                  {copied ? "Copied" : "Copy"}
                </button>
                <button
                  className="tool-action"
                  onClick={() => download(`${fileName}.md`, visibleMarkdown, "text/markdown")}
                >
                  <Download size={15} /> .md
                </button>
                <button
                  className="tool-action"
                  onClick={() => download(`${fileName}.txt`, visibleMarkdown, "text/plain")}
                >
                  <Download size={15} /> .txt
                </button>
              </div>
            )}
          </div>
          {stream.error && <div className="tool-error" role="alert">{stream.error}</div>}
          {copyError && <div className="tool-error" role="alert">{copyError}</div>}
          {stream.status && <div className="tool-status" role="status">{stream.status}</div>}
          {stream.loading && (
            <div className="tool-stream-indicator">
              <span className="typing-indicator"><i /><i /><i /></span>
              <span>Generating your result</span>
              <button className="tool-action" onClick={stream.stop} aria-label="Stop generation">
                <Square size={13} /> Stop
              </button>
            </div>
          )}
          {stream.result?.data?.truncated && (
            <p className="tool-truncated" role="status">Some input was shortened to fit the tool’s size limit.</p>
          )}
          {stream.result?.mode === "markdown_fallback" && (
            <div className="tool-fallback">{stream.result.markdown}</div>
          )}
          {!stream.result && stream.raw && <pre className="tool-live-output">{stream.raw}</pre>}
          {structured && renderResult(structured)}
          {!stream.result && !stream.raw && !stream.error && !stream.loading && (
            <div className="tool-empty">
              <Sparkles size={20} aria-hidden="true" />
              <span>Complete the form to see your result.</span>
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
