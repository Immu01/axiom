import { useCallback, useRef, useState } from "react";
import { streamToolRequest } from "./api.js";

export function useToolStream({ apiUrl, apiKey }) {
  const [loading, setLoading] = useState(false);
  const [raw, setRaw] = useState("");
  const [result, setResult] = useState(null);
  const [provider, setProvider] = useState("");
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [sources, setSources] = useState(null);
  const controllerRef = useRef(null);

  const run = useCallback(async (path, body) => {
    if (controllerRef.current) controllerRef.current.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setRaw("");
    setResult(null);
    setProvider("");
    setStatus("Connecting to Axiom…");
    setError("");
    setSources(null);
    try {
      await streamToolRequest({
        apiUrl,
        apiKey,
        path,
        body,
        signal: controller.signal,
        onEvent(event, data) {
          if (event === "meta") setProvider(data.provider || "");
          if (event === "status") setStatus(data.message || "Axiom is continuing…");
          if (event === "token") setRaw((text) => text + (data.text || ""));
          if (event === "result") {
            setResult(data);
            setStatus("");
          }
          if (event === "sources") setSources(data);
          if (event === "error") setError(data.message || "The model could not complete this request.");
        },
      });
    } catch (requestError) {
      if (requestError.name !== "AbortError") setError(requestError.message || "Could not reach Axiom.");
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
        setLoading(false);
        setStatus("");
      }
    }
  }, [apiKey, apiUrl]);

  const stop = useCallback(() => controllerRef.current?.abort(), []);

  return { loading, raw, result, provider, status, error, sources, run, stop };
}
