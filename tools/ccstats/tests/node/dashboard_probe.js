"use strict";
/* Headless harness for `dashboard_template.html`'s client-side JS.
 *
 * Before 2026-08-24 this file's JavaScript had ZERO test coverage - every one
 * of that day's four data-correctness defects (a double count, three blended
 * "session" populations, a wrong column, an unapplied exclude list) shipped
 * with a fully green `pytest` suite because nothing ever executed this
 * script. This harness runs the REAL generated <script> block (not a copy,
 * not a summary of it) against a minimal DOM stub, then reports back the
 * Overview tiles exactly as a browser would render them, plus enough
 * internal state (FS, state.kinds, kindCounts()) for a caller to assert
 * against an independently computed expectation.
 *
 * Usage: node dashboard_probe.js <path-to-generated-html> [<json-scenario>]
 * Prints one JSON object to stdout. Any panel that throws is caught and
 * reported (mirrors the page's own renderAll() try/catch) rather than
 * crashing the probe.
 *
 * <json-scenario>, if given, is applied to `state` AFTER the initial render
 * (from, to, kinds: [names], excludedCanonical: [names]) so a caller can
 * exercise a specific filter combination without reimplementing the page's
 * own state machine.
 */

const fs = require("fs");
const vm = require("vm");

const htmlPath = process.argv[2];
const scenarioJson = process.argv[3];
if (!htmlPath) {
  console.error("usage: node dashboard_probe.js <html> [<scenario-json>]");
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
 * Deliberately minimal: real enough for THIS page's exact usage (id lookups,
 * classList, dataset, innerHTML as an opaque string, one delegated
 * querySelectorAll target). Not a general DOM - a broader page rewrite would
 * need this extended, which is a feature: it forces a human to look. */

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
  };
  el.style = {
    _props: {},
    setProperty(k, v) { el.style._props[k] = v; },
    getPropertyValue(k) { return el.style._props[k] || ""; },
  };
  el.getBoundingClientRect = () => ({ top: 0, left: 0, width: 0, height: 0, bottom: 0, right: 0 });
  Object.defineProperty(el, "textContent", {
    get() { return el._text; }, set(v) { el._text = String(v); },
  });
  Object.defineProperty(el, "innerHTML", {
    get() { return el._html; }, set(v) { el._html = String(v); },
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

// The three "count as a session" checkboxes/labels the page's own JS queries
// by `.kind-item[data-kind]` and by id (`kind-mine` etc, `kind-n-mine` etc).
const KIND_NAMES = ["mine", "subagent", "automated"];
const kindItems = {};
const idRegistry = {};
KIND_NAMES.forEach((name) => {
  const checkbox = makeEl("input", { type: "checkbox" });
  const item = makeEl("label", { class: "kind-item", "data-kind": name });
  item.dataset.kind = name;
  item.querySelector = (sel) => (String(sel).includes("checkbox") ? checkbox : null);
  idRegistry["kind-" + name] = checkbox;
  idRegistry["kind-n-" + name] = makeEl("span", { id: "kind-n-" + name });
  kindItems[name] = item;
});

function getOrMakeById(id) {
  if (!idRegistry[id]) idRegistry[id] = makeEl("div", { id });
  return idRegistry[id];
}

const panelsContainer = getOrMakeById("panels");
const documentElementStub = makeEl("html");
const documentStub = {
  getElementById: (id) => getOrMakeById(id),
  createElement: (tag) => makeEl(tag),
  addEventListener() {},
  body: makeEl("body"),
  documentElement: documentElementStub,
  // No real layout engine here, so nothing has a meaningful bounding box -
  // the page's own setNavTop() already guards for exactly this (a null
  // querySelector result, or an element with no real getBoundingClientRect).
  querySelector() { return null; },
  querySelectorAll(sel) {
    if (sel === ".kind-item[data-kind]") return KIND_NAMES.map((n) => kindItems[n]);
    if (sel === ".panel") return [];
    return [];
  },
};

const consoleErrors = [];
const context = vm.createContext({
  document: documentStub,
  console: { log() {}, warn() {}, error: (...a) => consoleErrors.push(a.join(" ")) },
  setTimeout, clearTimeout,
  Math, Date, JSON, Set, Map, Array, Object, Number, String, Boolean, Intl,
  Proxy, RegExp,
});

// `vm.Script.runInContext` does NOT attach top-level `let`/`const` bindings
// as properties of the context object (only `var` would) - so `context.FS`
// etc would otherwise read as undefined even though the script ran fine.
// Appending an assignment INSIDE the same script text sidesteps this: it is
// still in the same top-level lexical scope as the real declarations, so it
// can reference them by name directly, and assigning to `globalThis` (which
// a sloppy-mode vm script sees as the context object) makes the values
// visible to this file afterward.
// FS/FS_set are REASSIGNED by recomputeFilteredSessions() (FS = [] etc), so
// capturing them by value here would go stale the moment renderAll() runs
// again for a scenario - expose accessor functions instead, which close
// over the live binding rather than a one-time snapshot of it.
const probeEpilogue = `
;globalThis.__probe = { state, KIND_IDX, PANELS, kindCounts, LK, IDX,
  CANON_PROJECT, CANON_LIST, renderAll, recomputeFilteredSessions, DATA,
  getFS: () => FS, getFS_set: () => FS_set };
`;

let runError = null;
try {
  new vm.Script(pageScript + probeEpilogue, { filename: "dashboard_template.html:script" })
    .runInContext(context);
} catch (err) {
  runError = String((err && err.stack) || err);
}
const probe = context.__probe || {};

const result = { runError, consoleErrors, panels: {}, kindCounts: null, filterSummary: null };

if (!runError) {
  // Apply an optional scenario, then re-render, mirroring what a reader
  // clicking the controls would trigger (minus the debounce timer).
  if (scenarioJson) {
    const scenario = JSON.parse(scenarioJson);
    const stateRef = probe.state;
    if (scenario.from) stateRef.from = scenario.from;
    if (scenario.to) stateRef.to = scenario.to;
    if (scenario.kinds) {
      stateRef.kinds = new Set(scenario.kinds.map((n) => probe.KIND_IDX[n]));
    }
    if (scenario.excludedCanonical) {
      stateRef.excluded = new Set(scenario.excludedCanonical);
    }
    probe.renderAll();
  }

  try {
    result.kindCounts = probe.kindCounts();
  } catch (err) {
    result.kindCounts = { error: String(err) };
  }
  result.filterSummary = documentStub.getElementById("f-summary").innerHTML;
  result.fsLength = probe.getFS().length;
  result.stateKinds = [...probe.state.kinds];
  result.stateExcluded = [...probe.state.excluded];

  probe.PANELS.forEach((p) => {
    try {
      const out = p.render();
      const tiles = {};
      const re = /<p class="kpi-v">([\s\S]*?)<\/p><p class="kpi-l">([\s\S]*?)<\/p>/g;
      let mm;
      while ((mm = re.exec(out.body))) { tiles[mm[2]] = mm[1]; }
      result.panels[p.id] = { ok: true, eyebrow: out.eyebrow, tiles };
    } catch (err) {
      result.panels[p.id] = { ok: false, error: String((err && err.stack) || err) };
    }
  });
}

process.stdout.write(JSON.stringify(result));
