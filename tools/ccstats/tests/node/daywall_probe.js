"use strict";
/* Headless harness for `daywall_template.html`'s PURE-DATA half only
 * (clipToDays, packLanes, recomputeFiltered) -- never the WebGL half, which
 * cannot run under Node at all. The canvas stub's getContext() returns null
 * on purpose, so boot() takes the documented no-WebGL fallback path and
 * never touches instBuf/program; the pure functions stay reachable and
 * callable directly regardless, because they are declared at the script's
 * top level, independent of whether boot() ran the WebGL branch.
 *
 * Usage: node daywall_probe.js <path-to-generated-html> [<json-scenario>]
 * <json-scenario>, if given, is applied to `state` BEFORE calling
 * recomputeFiltered() again (from, to, kinds: [names], excludedCanonical,
 * threads: bool), the same convention dashboard_probe.js uses.
 * Prints one JSON object to stdout.
 */

const fs = require("fs");
const vm = require("vm");

const htmlPath = process.argv[2];
const scenarioJson = process.argv[3];
if (!htmlPath) {
  console.error("usage: node daywall_probe.js <html> [<scenario-json>]");
  process.exit(2);
}

const html = fs.readFileSync(htmlPath, "utf-8");
const m = html.match(/<script>\n([\s\S]*)<\/script>\n<\/body>/);
if (!m) {
  console.error("could not find the page's own <script> block");
  process.exit(2);
}
const pageScript = m[1];

/* ---------------------------------------------------------------- DOM stub
 * Minimal: real enough for THIS page's boot()-time DOM touches (id lookups,
 * classList, dataset, innerHTML as an opaque string) so the script runs to
 * completion without throwing. Not a general DOM. */

function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    toggle: (c, force) => {
      if (force === undefined) { set.has(c) ? set.delete(c) : set.add(c); }
      else if (force) { set.add(c); } else { set.delete(c); }
    },
    contains: (c) => set.has(c),
  };
}

function makeEl(tag, attrs) {
  attrs = attrs || {};
  const el = {
    tagName: String(tag).toUpperCase(),
    _attrs: Object.assign({}, attrs),
    _text: "", _html: "",
    _listeners: {},
    classList: makeClassList(),
    checked: false,
    value: "",
    min: "", max: "",
    addEventListener(type, fn) { (el._listeners[type] = el._listeners[type] || []).push(fn); },
    dispatch(type, evt) { (el._listeners[type] || []).forEach((fn) => fn(evt)); },
    getAttribute(k) { return el._attrs[k]; },
    setAttribute(k, v) { el._attrs[k] = v; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    closest() { return null; },
    focus() {},
    appendChild(child) { el._children = el._children || []; el._children.push(child); return child; },
    remove() {},
    replaceWith() {},
    getContext() { return null; },
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 }),
  };
  el.style = {
    _props: {},
    setProperty(k, v) { el.style._props[k] = v; },
    getPropertyValue(k) { return el.style._props[k] || ""; },
  };
  Object.defineProperty(el, "textContent", {
    get() { return el._text; }, set(v) { el._text = String(v); },
  });
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; }, set(v) { el._html += String(v); },
  });
  el.dataset = new Proxy({}, {
    get(_, k) {
      const attr = "data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
      return el._attrs[attr];
    },
    set(_, k, v) {
      const attr = "data-" + String(k).replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
      el._attrs[attr] = v;
      return true;
    },
  });
  return el;
}

const idRegistry = {};
function getOrMakeById(id) {
  if (!idRegistry[id]) idRegistry[id] = makeEl("div", { id });
  return idRegistry[id];
}

const documentElementStub = makeEl("html");
const documentStub = {
  getElementById: (id) => getOrMakeById(id),
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
  body: makeEl("body"),
  documentElement: documentElementStub,
  querySelector() { return null; },
  querySelectorAll() { return []; },
};

const windowStub = {
  addEventListener() {},
  devicePixelRatio: 1,
  innerWidth: 800,
  innerHeight: 600,
};

const consoleErrors = [];
const context = vm.createContext({
  document: documentStub,
  window: windowStub,
  console: { log() {}, warn() {}, error: (...a) => consoleErrors.push(a.join(" ")) },
  setTimeout, clearTimeout, requestAnimationFrame: () => 0,
  Math, Date, JSON, Set, Map, Array, Object, Number, String, Boolean, Intl,
  Proxy, RegExp, Float32Array, Uint8Array, Infinity,
});

// See dashboard_probe.js for why this trick is needed: vm.Script does not
// attach top-level let/const bindings to the context object, so everything
// the probe needs is re-exported explicitly, inside the SAME script text
// (same lexical scope), rather than relied on to appear as a global.
const probeEpilogue = `
;globalThis.__probe = { state, DATA, IDX, LK, CANON_PROJECT, CANON_LIST, KIND_IDX,
  clipToDays, packLanes, recomputeFiltered };
`;

let runError = null;
try {
  new vm.Script(pageScript + probeEpilogue, { filename: "daywall_template.html:script" })
    .runInContext(context);
} catch (err) {
  runError = String((err && err.stack) || err);
}
const probe = context.__probe || {};

const result = { runError, consoleErrors };
const scenario = scenarioJson ? JSON.parse(scenarioJson) : null;

if (!runError) {
  if (scenario) {
    const stateRef = probe.state;
    if (scenario.from) stateRef.from = scenario.from;
    if (scenario.to) stateRef.to = scenario.to;
    if (scenario.kinds) {
      stateRef.kinds = new Set(scenario.kinds.map((n) => probe.KIND_IDX[n]));
    }
    if (scenario.excludedCanonical) {
      stateRef.excluded = new Set(scenario.excludedCanonical);
    }
    if (scenario.threads !== undefined) {
      stateRef.threads = scenario.threads;
    }
  }

  try {
    const filtered = probe.recomputeFiltered();
    result.sessionCount = filtered.sessionCount;
    result.maxLanes = filtered.maxLanes;
    result.dayCount = filtered.dayCount;
    result.draw = filtered.draw;
    result.threads = filtered.threads;
  } catch (err) {
    result.recomputeError = String((err && err.stack) || err);
  }

  // Functions cannot survive JSON.stringify, so clipToDays/packLanes are
  // never handed back AS functions -- the scenario instead names specific
  // CASES to run through the real page's own implementation, and the probe
  // returns the computed results.
  if (scenario && scenario.clipToDaysCases) {
    result.clipToDaysResults = scenario.clipToDaysCases.map(
      ([dayIdx, startSec, durSec]) => probe.clipToDays(dayIdx, startSec, durSec)
    );
  }
  if (scenario && scenario.packLanesCases) {
    result.packLanesResults = scenario.packLanesCases.map((segs) => probe.packLanes(segs));
  }
}

process.stdout.write(JSON.stringify(result));
