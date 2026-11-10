const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const vm = require("node:vm");
const ts = require("typescript");

const compiled = ts.transpileModule(readFileSync(path.join(__dirname, "../lib/text.ts"), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;

function load(globals = {}) {
  const exports = {};
  vm.runInNewContext(compiled, { exports, ...globals });
  return exports;
}

test("clipText leaves short text untouched", () => {
  assert.equal(load().clipText("hola", 10), "hola");
  assert.equal(load().clipText("hola", 4), "hola");
});

test("clipText truncates to the limit", () => {
  assert.equal(load().clipText("abcdef", 3), "abc");
});

test("clipText never leaves a lone high surrogate at the end", () => {
  const text = "ab😀cd"; // the emoji is two UTF-16 units at indexes 2-3
  assert.equal(load().clipText(text, 3), "ab");
  assert.equal(load().clipText(text, 4), "ab😀");
});

test("copyText uses the async clipboard in a secure context", async () => {
  const written = [];
  const copy = load({
    navigator: { clipboard: { writeText: async (value) => written.push(value) } },
    window: { isSecureContext: true },
  }).copyText;
  assert.equal(await copy("texto"), true);
  assert.deepEqual(written, ["texto"]);
});

function fakeDocument(execResult) {
  const area = {
    style: {},
    setAttribute() {},
    select() {},
    remove() {
      area.removed = true;
    },
  };
  return {
    area,
    document: {
      createElement: () => area,
      body: { appendChild() {} },
      execCommand: () => {
        if (execResult instanceof Error) throw execResult;
        return execResult;
      },
    },
  };
}

test("copyText falls back to execCommand outside secure contexts", async () => {
  const { area, document } = fakeDocument(true);
  const copy = load({ navigator: {}, window: { isSecureContext: false }, document }).copyText;
  assert.equal(await copy("texto"), true);
  assert.equal(area.value, "texto");
  assert.equal(area.removed, true);
});

test("copyText falls back when the async clipboard rejects, and reports failure", async () => {
  const { area, document } = fakeDocument(new Error("blocked"));
  const copy = load({
    navigator: {
      clipboard: {
        writeText: async () => {
          throw new Error("denied");
        },
      },
    },
    window: { isSecureContext: true },
    document,
  }).copyText;
  assert.equal(await copy("texto"), false);
  assert.equal(area.removed, true);
});
