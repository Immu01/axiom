import { useState } from "react";
import { ClipboardList, Upload } from "lucide-react";
import ToolPanel from "./ToolPanel.jsx";
import { useToolStream } from "./useToolStream.js";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

function MeetingReport({ result }) {
  const [actions, setActions] = useState(result.action_items || []);
  return (
    <div className="meeting-report">
      <h3>{result.title}</h3>
      <p>{result.summary}</p>
      <h3>Decisions</h3>
      {result.decisions.length ? result.decisions.map((item, index) => (
        <article className="tool-result-card" key={`${item.decision}-${index}`}>
          <b>{item.decision}</b>{item.evidence && <small>Evidence: “{item.evidence}”</small>}
        </article>
      )) : <p>No confirmed decisions were identified.</p>}
      <h3>Action items · editable</h3>
      {actions.length ? actions.map((item, index) => (
        <article className="tool-result-card" key={`${index}-${item.task}`}>
          <label className="tool-label">Task<input value={item.task} onChange={(event) => setActions((items) => items.map((action, i) => i === index ? { ...action, task: event.target.value } : action))} /></label>
          <div className="tool-field-grid">
            <label className="tool-label">Owner<input value={item.owner || ""} placeholder="Not specified" onChange={(event) => setActions((items) => items.map((action, i) => i === index ? { ...action, owner: event.target.value || null } : action))} /></label>
            <label className="tool-label">Due date<input value={item.due_date || ""} placeholder="Not specified" onChange={(event) => setActions((items) => items.map((action, i) => i === index ? { ...action, due_date: event.target.value || null } : action))} /></label>
          </div>
          <small>{item.status} · {item.evidence || "No transcript excerpt was included."}</small>
        </article>
      )) : <p>No explicit action items were identified.</p>}
      <h3>Open questions</h3>
      <ul>{result.open_questions.map((item, index) => <li key={index}>{item}</li>)}</ul>
      {result.risks.length > 0 && <><h3>Risks</h3><ul>{result.risks.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
      <h3>Follow-up email</h3>
      <pre className="tool-code-output">{result.follow_up_email}</pre>
    </div>
  );
}

export default function MeetingNotesTool({ apiKey }) {
  const stream = useToolStream({ apiUrl: API_URL, apiKey });
  const [transcript, setTranscript] = useState("");
  const [title, setTitle] = useState("");
  const [file, setFile] = useState(null);

  function submit(event) {
    event.preventDefault();
    if (file) {
      const form = new FormData();
      form.append("file", file);
      form.append("title", title);
      stream.run("/api/tools/meeting/upload", form);
    } else {
      stream.run("/api/tools/meeting/analyze", { transcript, title });
    }
  }

  return (
    <ToolPanel
      title="Meeting Notes"
      description="Turn a transcript into evidence-based notes, decisions, editable action items, and a follow-up email."
      stream={stream}
      renderResult={(result) => <MeetingReport key={result.summary} result={result} />}
      fileName="axiom-meeting-notes"
    >
      <form onSubmit={submit}>
        <div className="tool-form-title"><ClipboardList size={18} /><h2>Meeting transcript</h2></div>
        <label className="tool-label" htmlFor="meeting-title">Meeting title (optional)</label>
        <input id="meeting-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Weekly planning" />
        <label className="tool-label" htmlFor="meeting-transcript">Paste transcript</label>
        <textarea id="meeting-transcript" value={transcript} onChange={(event) => { setTranscript(event.target.value); setFile(null); }} placeholder="Paste speaker-labeled meeting notes or transcript…" rows={16} />
        <div className="tool-upload-row">
          <input type="file" accept=".pdf,.docx,.txt,.md,.csv" onChange={(event) => setFile(event.target.files?.[0] || null)} aria-label="Upload a transcript document" />
          <span>{file ? file.name : "Optional PDF, DOCX, TXT, Markdown, or CSV"}</span>
        </div>
        <p className="tool-status">Unassigned owners and dates are left unspecified; transcripts are not saved.</p>
        <button className="tool-submit" type="submit" disabled={stream.loading || (!file && !transcript.trim())}>
          <Upload size={16} /> Generate meeting notes
        </button>
      </form>
    </ToolPanel>
  );
}
