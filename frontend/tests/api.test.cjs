const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

// Compile the API module in isolation so tests use Node's real UTF-8 stream primitives.
const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "../lib/api.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function api(fetch, extra = {}) {
  const exports = {};
  vm.runInNewContext(compiled, { exports, fetch, process: { env: {} }, TextDecoder, ...extra });
  return exports;
}

// Runs timers immediately and records the delays that were requested.
function instantTimers() {
  const delays = [];
  const setTimeoutNow = (callback, ms) => {
    delays.push(ms);
    queueMicrotask(callback);
    return delays.length;
  };
  return { delays, extra: { setTimeout: setTimeoutNow, clearTimeout() {} } };
}

const done = { type: "done", translation: "Wie geht's, süßer Käse?", source: "es", target: "de" };
const args = ["¿Qué tal, queso dulce?", "es", "de"];
const encode = (value) => new TextEncoder().encode(value);
const record = (value) => JSON.stringify(value) + "\n";

function streamed(chunks) {
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks)
          controller.enqueue(typeof chunk === "string" ? encode(chunk) : chunk);
        controller.close();
      },
    }),
    { headers: { "Content-Type": "application/x-ndjson" } }
  );
}

test("sends text, source and target as JSON to the stream endpoint", async () => {
  const calls = [];
  const translate = api(async (url, options) => {
    calls.push({ url, options });
    return streamed([record(done)]);
  }).translateStream;
  await translate(...args, () => {});
  assert.ok(calls[0].url.endsWith("/api/translate/stream"));
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    text: args[0],
    source: "es",
    target: "de",
  });
});

test("streams non-ASCII text across arbitrary byte boundaries and accepts a final record without newline", async () => {
  const bytes = encode(
    record({ type: "delta", text: "Wie geht's, " }) +
      "\r\n" +
      record({ type: "delta", text: "süßer Käse?" }) +
      JSON.stringify(done)
  );
  const deltas = [];
  const result = await api(async () =>
    streamed(Array.from(bytes, (byte) => Uint8Array.of(byte)))
  ).translateStream(...args, (text) => deltas.push(text));
  assert.deepEqual(deltas, ["Wie geht's, ", "süßer Käse?"]);
  assert.equal(result.translation, done.translation);
});

test("delivers partial output while the server is still generating", async () => {
  let controller;
  const response = new Response(
    new ReadableStream({
      start(value) {
        controller = value;
      },
    })
  );
  let sawDelta;
  const partial = new Promise((resolve) => {
    sawDelta = resolve;
  });
  let finished = false;
  const result = api(async () => response)
    .translateStream(...args, sawDelta)
    .then((value) => {
      finished = true;
      return value;
    });
  controller.enqueue(encode(record({ type: "delta", text: "Wie geht's" })));
  assert.equal(await partial, "Wie geht's");
  assert.equal(finished, false);
  controller.enqueue(encode(record(done)));
  assert.equal((await result).translation, done.translation);
});

test("truncated output cannot be mistaken for a successful translation", async () => {
  const translate = api(async () =>
    streamed([record({ type: "delta", text: "Partial" })])
  ).translateStream;
  await assert.rejects(
    translate(...args, () => {}),
    /interrumpió antes de terminar/
  );
});

test("stream errors after partial output reject and never retry", async () => {
  let calls = 0;
  const translate = api(async () => {
    calls++;
    return streamed([
      record({ type: "delta", text: "Partial" }) +
        record({ type: "error", detail: "La traducción ha fallado.", status: 500 }),
    ]);
  }).translateStream;
  await assert.rejects(
    translate(...args, () => {}),
    /La traducción ha fallado/
  );
  assert.equal(calls, 1);
});

test("abort prevents later buffered deltas and completion from updating a stale request", async () => {
  const abort = new AbortController();
  const deltas = [];
  const translate = api(async () =>
    streamed([
      record({ type: "delta", text: "First" }) +
        record({ type: "delta", text: "Stale" }) +
        record(done),
    ])
  ).translateStream;
  await assert.rejects(
    translate(
      ...args,
      (delta) => {
        deltas.push(delta);
        abort.abort();
      },
      abort.signal
    ),
    { name: "AbortError" }
  );
  assert.deepEqual(deltas, ["First"]);
});

test("HTTP validation, limits and inference errors surface the server detail and never retry", async () => {
  for (const status of [400, 413, 422, 500]) {
    let calls = 0;
    const translate = api(async () => {
      calls++;
      return Response.json({ detail: "Request failed" }, { status });
    }).translateStream;
    await assert.rejects(
      translate(...args, () => {}),
      /Request failed/
    );
    assert.equal(calls, 1);
  }
});

test("malformed records and invalid done events fail instead of caching a partial result", async () => {
  for (const record of ["not-json\n", '{"type":"done"}\n', '{"type":"unexpected"}\n']) {
    await assert.rejects(
      api(async () => streamed([record])).translateStream(...args, () => {}),
      /no es válida/
    );
  }
});

const busy = (retryAfter) =>
  Response.json(
    { detail: "El servidor está ocupado." },
    {
      status: 503,
      headers: retryAfter === undefined ? {} : { "Retry-After": String(retryAfter) },
    }
  );

test("a busy server (503) is retried after Retry-After and then succeeds", async () => {
  const timers = instantTimers();
  const answers = [busy(3), streamed([record(done)])];
  let calls = 0;
  const result = await api(async () => answers[calls++], timers.extra).translateStream(
    ...args,
    () => {}
  );
  assert.equal(result.translation, done.translation);
  assert.equal(calls, 2);
  assert.deepEqual(timers.delays, [3000]);
});

test("busy retries are capped, bounded in delay, and the last answer surfaces its detail", async () => {
  const timers = instantTimers();
  let calls = 0;
  const translate = api(async () => (calls++, busy(60)), timers.extra).translateStream;
  await assert.rejects(
    translate(...args, () => {}),
    /ocupado/
  );
  assert.equal(calls, 3);
  assert.deepEqual(timers.delays, [10000, 10000]);
});

test("a missing Retry-After falls back to a default delay", async () => {
  const timers = instantTimers();
  const answers = [busy(), streamed([record(done)])];
  let calls = 0;
  await api(async () => answers[calls++], timers.extra).translateStream(...args, () => {});
  assert.deepEqual(timers.delays, [5000]);
});

test("aborting while waiting for a busy server stops the retry", async () => {
  const abort = new AbortController();
  let calls = 0;
  const translate = api(async () => (calls++, busy(5)), {
    setTimeout: () => 1,
    clearTimeout() {},
  }).translateStream;
  const pending = translate(...args, () => {}, abort.signal);
  await new Promise((resolve) => setImmediate(resolve));
  abort.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(calls, 1);
});

test("languages are requested once, shared, and a failure can be retried", async () => {
  let calls = 0;
  const info = {
    source: { code: "es", name: "Español" },
    targets: [],
    max_input_chars: 10,
    docs_enabled: true,
  };
  const { fetchLanguages } = api(async () => {
    calls++;
    return calls === 1 ? new Response("", { status: 502 }) : Response.json(info);
  });
  await assert.rejects(fetchLanguages(), /idiomas/);
  const [first, second] = await Promise.all([fetchLanguages(), fetchLanguages()]);
  assert.deepEqual(first, info);
  assert.equal(first, second);
  assert.equal(calls, 2);
  await fetchLanguages();
  assert.equal(calls, 2);
});
