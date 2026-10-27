import { useCallback, useEffect, useRef, useState } from "react";
import { BookOpen, FileSearch, Trash2, Upload } from "lucide-react";
import ToolPanel from "./ToolPanel.jsx";
import { useToolStream } from "./useToolStream.js";

const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
let documentCache = null;
let documentRequest = null;

async function jsonRequest(path, apiKey, options = {}) {
  const headers = { ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) };
  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status}).`);
  return payload;
}

async function loadDocuments(apiKey, force = false) {
  if (
    !force
    && documentCache?.apiKey === apiKey
    && Date.now() - documentCache.loadedAt < 15_000
  ) {
    return documentCache.documents;
  }
  if (!force && documentRequest?.apiKey === apiKey) return documentRequest.promise;
  const promise = jsonRequest("/api/tools/pdf/documents", apiKey);
  const request = { apiKey, promise };
  if (!force) documentRequest = request;
  try {
    const payload = await promise;
    documentCache = { apiKey, documents: payload.documents || [], loadedAt: Date.now() };
    return documentCache.documents;
  } finally {
    if (documentRequest === request) documentRequest = null;
  }
}

function PDFResult({ result, sources }) {
  if (result.answer) {
    return (
      <div className="pdf-answer">
        <p>{result.answer}</p>
        <p className="tool-status">Search method: {result.retrieval_mode === "hybrid" ? "AI and keyword search" : "Keyword search"} · Query: {result.rewritten_query}</p>
        {result.retrieval_inspector?.length > 0 && (
          <details className="pdf-inspector">
            <summary>Source details · {result.retrieval_inspector.length} passages</summary>
            {result.retrieval_inspector.map((source) => (
              <article className="tool-result-card" key={`${source.doc_id}-${source.page}-${source.id}`}>
                <b>[{source.id}] {source.doc_name} · page {source.page}</b>
                {source.similarity > 0 && <small>Match score: {Math.round(source.similarity * 100)}%</small>}
                <p>{source.snippet}</p>
              </article>
            ))}
          </details>
        )}
      </div>
    );
  }
  return (
    <div className="pdf-study-result">
      <h3>Study summary</h3><p>{result.summary}</p>
      <h3>Key concepts</h3><ul>{result.key_concepts?.map((item, index) => <li key={index}>{item.concept} <small>(page {item.page})</small></li>)}</ul>
      <h3>Glossary</h3>{result.glossary?.map((item, index) => <p key={index}><b>{item.term}</b>: {item.definition} <small>(page {item.page})</small></p>)}
      <h3>Flashcards</h3>{result.flashcards?.map((item, index) => <article className="tool-result-card" key={index}><b>{item.front}</b><p>{item.back}</p><small>Page {item.page}</small></article>)}
      <h3>Quiz</h3>{result.quiz?.map((item, index) => <article className="tool-result-card" key={index}><b>{item.question}</b><p>{item.answer}</p><small>Page {item.page}</small></article>)}
      {sources?.items?.length > 0 && <p className="tool-status">Grounded in {sources.items.length} passages.</p>}
    </div>
  );
}

export default function PdfTutorTool({ apiKey }) {
  const stream = useToolStream({ apiUrl: API_URL, apiKey });
  const [files, setFiles] = useState([]);
  const [documents, setDocuments] = useState([]);
  const [selectedIds, setSelectedIds] = useState([]);
  const [question, setQuestion] = useState("");
  const [uploading, setUploading] = useState(false);
  const [documentError, setDocumentError] = useState("");
  const [uploadNotice, setUploadNotice] = useState("");
  const [allowOutside, setAllowOutside] = useState(false);
  const [tutorLevel, setTutorLevel] = useState("beginner");
  const fileInput = useRef(null);

  const refreshDocuments = useCallback(async () => {
    try {
      const nextDocuments = await loadDocuments(apiKey, true);
      setDocuments(nextDocuments);
      setSelectedIds((current) => current.filter((id) => nextDocuments.some((doc) => doc.id === id)));
      setDocumentError("");
    } catch (error) {
      setDocumentError(error.message);
    }
  }, [apiKey]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const nextDocuments = await loadDocuments(apiKey);
        if (!active) return;
        setDocuments(nextDocuments);
        setDocumentError("");
      } catch (error) {
        if (active) setDocumentError(error.message);
      }
    }
    void load();
    return () => { active = false; };
  }, [apiKey]);

  async function upload(event) {
    event.preventDefault();
    if (!files.length) return;
    setUploading(true);
    setDocumentError("");
    setUploadNotice("");
    const form = new FormData();
    files.forEach((file) => form.append("files", file));
    try {
      const payload = await jsonRequest("/api/tools/pdf/upload", apiKey, { method: "POST", body: form });
      const documentsWithFallback = (payload.documents || []).filter((doc) => doc.retrieval_mode === "fts").length;
      const truncatedDocuments = (payload.documents || []).filter((doc) => doc.truncated).length;
      setUploadNotice([
        `${payload.documents?.length || 0} PDF(s) indexed.`,
        documentsWithFallback ? "Keyword-only retrieval is active where embeddings were unavailable." : "",
        truncatedDocuments ? "Some extracted text was shortened to the configured limit." : "",
      ].filter(Boolean).join(" "));
      setFiles([]);
      if (fileInput.current) fileInput.current.value = "";
      await refreshDocuments();
    } catch (error) {
      setDocumentError(error.message);
    } finally {
      setUploading(false);
    }
  }

  async function removeDocument(docId) {
    try {
      await jsonRequest(`/api/tools/pdf/documents/${encodeURIComponent(docId)}`, apiKey, { method: "DELETE" });
      await refreshDocuments();
    } catch (error) {
      setDocumentError(error.message);
    }
  }

  function ask(event) {
    event.preventDefault();
    if (!question.trim()) return;
    stream.run("/api/tools/pdf/chat", {
      question,
      doc_ids: selectedIds,
      allow_outside_knowledge: allowOutside,
      tutor_mode: true,
      tutor_level: tutorLevel,
    });
  }

  function createStudyMaterial(mode) {
    if (!documents.length) return;
    const docId = selectedIds[0] || documents[0].id;
    stream.run("/api/tools/pdf/tutor", { doc_id: docId, mode, tutor_level: tutorLevel });
  }

  return (
    <ToolPanel
      title="PDF Tutor"
      description="Upload PDFs, ask questions with page citations, and create study materials. Your extracted text is stored privately for search."
      stream={stream}
      renderResult={(result) => <PDFResult result={result} sources={stream.sources} />}
      fileName="axiom-pdf-study-guide"
    >
      <form onSubmit={upload}>
        <div className="tool-form-title"><FileSearch size={18} /><h2>Your PDF library</h2></div>
        <label className="tool-label" htmlFor="pdf-files">Add PDF documents</label>
        <input ref={fileInput} id="pdf-files" type="file" accept="application/pdf,.pdf" multiple onChange={(event) => setFiles(Array.from(event.target.files || []))} />
        <p className="tool-status">PDFs up to 10 MB each · extracted text and optional embeddings are stored for retrieval. Scanned PDFs need OCR first.</p>
        <button className="tool-submit" type="submit" disabled={uploading || !files.length}><Upload size={16} />{uploading ? "Indexing PDFs…" : "Upload and index"}</button>
      </form>
      {documentError && <div className="tool-error" role="alert">{documentError}</div>}
      {uploadNotice && <p className="tool-status" role="status">{uploadNotice}</p>}
      <section className="pdf-document-list" aria-label="Indexed PDFs">
        <h3>Indexed documents</h3>
        {documents.length ? documents.map((doc) => (
          <div className="pdf-document-row" key={doc.id}>
            <label><input type="checkbox" aria-label={`Include ${doc.name} in questions`} checked={!selectedIds.length || selectedIds.includes(doc.id)} onChange={() => setSelectedIds((ids) => {
              const active = ids.length ? ids : documents.map((item) => item.id);
              const next = active.includes(doc.id) ? active.filter((id) => id !== doc.id) : [...active, doc.id];
              return next.length === documents.length ? [] : next;
            })} /><span>{doc.name}<small>{doc.chunks} indexed chunks</small></span></label>
            <button className="tool-action" type="button" onClick={() => removeDocument(doc.id)} aria-label={`Delete ${doc.name}`}><Trash2 size={14} /></button>
          </div>
        )) : <p>No PDFs indexed yet.</p>}
      </section>
      <form onSubmit={ask}>
        <div className="tool-form-title"><BookOpen size={18} /><h2>Ask your PDFs</h2></div>
        <label className="tool-label" htmlFor="pdf-question">Question</label>
        <textarea id="pdf-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What are the main arguments in chapter 2?" rows={5} />
        <label className="tool-label">Tutor level<select value={tutorLevel} onChange={(event) => setTutorLevel(event.target.value)}><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>
        <label className="tool-label pdf-checkbox"><input type="checkbox" checked={allowOutside} onChange={(event) => setAllowOutside(event.target.checked)} />Allow clearly labeled outside knowledge</label>
        <button className="tool-submit" type="submit" disabled={stream.loading || !question.trim() || !documents.length}>Ask with page citations</button>
        <div className="tool-field-grid">
          {["study_guide", "flashcards", "quiz"].map((mode) => <button className="tool-action" type="button" key={mode} onClick={() => createStudyMaterial(mode)} disabled={stream.loading || !documents.length}>{mode.replaceAll("_", " ")}</button>)}
        </div>
      </form>
    </ToolPanel>
  );
}
