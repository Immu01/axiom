import assert from "node:assert/strict";
import { parseSseFrame } from "./api.js";

assert.deepEqual(parseSseFrame('event: result\ndata: {"mode":"structured"}'), {
  event: "result",
  data: { mode: "structured" },
});
assert.deepEqual(parseSseFrame('data: {"text":"hello"}'), {
  event: "message",
  data: { text: "hello" },
});
assert.equal(parseSseFrame(": keepalive"), null);
assert.equal(parseSseFrame("event: ping"), null);
console.log("tool SSE parser ok");
