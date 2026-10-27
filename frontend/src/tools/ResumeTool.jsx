import { useRef, useState } from "react";
import { BriefcaseBusiness, Check, Copy, Upload } from "lucide-react";
import ToolPanel from "./ToolPanel.jsx";
import { useToolStream } from "./useToolStream.js";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

function ResumeReport({ result }) {
  const [copiedBullet, setCopiedBullet] = useState(-1);
  const [copyError, setCopyError] = useState("");

  async function copyBullet(bullet, index) {
    try {
      await navigator.clipboard.writeText(bullet.improved);
      setCopiedBullet(index);
      setCopyError("");
      setTimeout(() => setCopiedBullet(-1), 1500);
    } catch {
      setCopiedBullet(-1);
      setCopyError("Could not copy this suggestion. Check clipboard permissions and try again.");
    }
  }

  const categories = Object.entries(result.score_breakdown || {});
  return (
    <div className="resume-report">
      <div className="resume-score">
        <div className="resume-score-gauge" style={{ "--score": `${result.overall_score}%` }}>
          <span className="resume-score-number">{result.overall_score}</span>
        </div>
        <span>ATS readiness score / 100</span>
      </div>
      <div className="resume-breakdown">
        {categories.map(([name, value]) => (
          <div className="resume-score-row" key={name}>
            <span>{name.replaceAll("_", " ")}</span>
            <div className="resume-meter"><i style={{ width: `${value.score}%` }} /></div>
            <b>{value.score}</b>
            <small>{value.justification}</small>
          </div>
        ))}
      </div>
      <h3>Job-description keywords</h3>
      <div className="keyword-chips">
        {result.ats_keywords.matched.map((word) => <span className="keyword matched" key={word}>{word}</span>)}
        {result.ats_keywords.missing_critical.map((word) => <span className="keyword missing" key={word.keyword}>{word.keyword} · {word.where_to_add}</span>)}
        {result.ats_keywords.missing_nice_to_have.map((word) => <span className="keyword optional" key={word.keyword}>{word.keyword} · {word.where_to_add}</span>)}
      </div>
      <h3>Strengths and gaps</h3>
      <div className="resume-evidence-grid">
        {[["Strengths", result.strengths], ["Gaps", result.gaps]].map(([title, items]) => (
          <div className="tool-result-card" key={title}>
            <h4>{title}</h4>
            {items.map((item, index) => <p key={index}>{item.finding} <q>{item.resume_snippet}</q></p>)}
          </div>
        ))}
      </div>
      <h3>Improved bullets</h3>
      {copyError && <p className="tool-error" role="alert">{copyError}</p>}
      {result.improved_bullets.map((bullet, index) => (
        <article className="tool-result-card resume-bullet-card" key={`${index}-${bullet.improved}`}>
          {bullet.original && <p><b>Original:</b> {bullet.original}</p>}
          <p><b>Suggested:</b> {bullet.improved}</p>
          <small>{bullet.why}{bullet.contains_placeholder_metric ? " Verify the placeholder before using." : ""}</small>
          <button className="tool-action" onClick={() => copyBullet(bullet, index)} aria-label={`Copy improved bullet ${index + 1}`}>
            {copiedBullet === index ? <Check size={14} /> : <Copy size={14} />}
            {copiedBullet === index ? "Copied" : "Copy bullet"}
          </button>
        </article>
      ))}
      <h3>Tailored summary</h3>
      <p>{result.summary_suggestion}</p>
      <h3>Next steps</h3>
      <ol>{result.next_steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
    </div>
  );
}

export default function ResumeTool({ apiKey }) {
  const stream = useToolStream({ apiUrl: API_URL, apiKey });
  const [resume, setResume] = useState("");
  const [job, setJob] = useState("");
  const [role, setRole] = useState("");
  const [seniority, setSeniority] = useState("");
  const [file, setFile] = useState(null);
  const fileRef = useRef(null);

  function submit(event) {
    event.preventDefault();
    if (!job.trim() || (!file && !resume.trim())) return;
    if (file) {
      const form = new FormData();
      form.append("file", file);
      form.append("job_description", job);
      form.append("target_role", role);
      form.append("seniority", seniority);
      stream.run("/api/tools/resume/upload", form);
    } else {
      stream.run("/api/tools/resume/analyze", {
        resume_text: resume,
        job_description: job,
        target_role: role,
        seniority,
      });
    }
  }

  return (
    <ToolPanel
      title="Resume Analyzer"
      description="Compare your resume with a job description and get evidence-based, ATS-aware suggestions."
      stream={stream}
      renderResult={(result) => <ResumeReport result={result} />}
      fileName="axiom-resume-report"
    >
      <form onSubmit={submit}>
        <div className="tool-form-title"><BriefcaseBusiness size={18} /><h2>Your materials</h2></div>
        <label className="tool-label" htmlFor="resume-text">Resume text</label>
        <textarea id="resume-text" value={resume} onChange={(event) => { setResume(event.target.value); setFile(null); }} placeholder="Paste your resume here…" rows={9} />
        <div className="tool-upload-row">
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.txt"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
            aria-label="Choose a PDF, DOCX, or TXT resume"
          />
          <span>{file ? file.name : "PDF, DOCX, TXT · processed in memory"}</span>
        </div>
        <label className="tool-label" htmlFor="resume-job">Job description</label>
        <textarea id="resume-job" value={job} onChange={(event) => setJob(event.target.value)} placeholder="Paste the job description. Keywords come only from this text." rows={8} />
        <div className="tool-field-grid">
          <label className="tool-label">Target role<input value={role} onChange={(event) => setRole(event.target.value)} placeholder="e.g. Backend Engineer" /></label>
          <label className="tool-label">Seniority<input value={seniority} onChange={(event) => setSeniority(event.target.value)} placeholder="e.g. Mid-level" /></label>
        </div>
        <button className="tool-submit" type="submit" disabled={stream.loading || !job.trim() || (!file && !resume.trim())}>
          <Upload size={16} /> Analyze resume
        </button>
      </form>
    </ToolPanel>
  );
}
