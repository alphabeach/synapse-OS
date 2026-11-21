// app.js -- shell: api client (with CSRF), ctx, router, login, nav.
// Views import only ./ui.js; this file is the single place that knows the shell.
import * as dashboard from "./dashboard.js";
import * as inventory from "./inventory.js";
import * as quotes from "./quotes.js";
import * as customs from "./customs.js";

import { el, rank } from "./ui.js";

const VIEWS = [dashboard, inventory, quotes, customs];
const BY_ID = new Map(VIEWS.map((m) => [m.view.id, m]));

const state = { me: null, current: null };
const $ = (sel) => document.querySelector(sel);

// --------------------------------------------------------------------------- //
// API: cookie session + double-submit CSRF header on every mutation.
// --------------------------------------------------------------------------- //
function csrf() {
  const match = document.cookie.match(/(?:^|;\s*)exin_csrf=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request(method, path, body) {
  const opts = { method, headers: {}, credentials: "same-origin" };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  if (method !== "GET") opts.headers["X-CSRF-Token"] = csrf();

  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    showLogin();
    throw new Error("Your session ended. Sign in again.");
  }
  if (!res.ok) {
    const err = new Error(data.detail || res.statusText || "Request failed");
    err.status = res.status;
    throw err;
  }
  return data;
}

const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body),
  patch: (path, body) => request("PATCH", path, body),
};

// --------------------------------------------------------------------------- //
// Toast
// --------------------------------------------------------------------------- //
function toast(message, kind = "ok") {
  const host = $("#toasts");
  const node = el("div", { class: `toast ${kind}`, role: "status" }, message);
  host.append(node);
  setTimeout(() => node.remove(), 3200);
}

// --------------------------------------------------------------------------- //
// ctx -- what a view receives. No view touches auth state directly.
// --------------------------------------------------------------------------- //
const ctx = {
  get me() { return state.me; },
  api,
  toast,
  navigate: (id) => navigate(id),
  can: (minimum) => rank(state.me && state.me.role) >= rank(minimum),
};

// --------------------------------------------------------------------------- //
// Screens
// --------------------------------------------------------------------------- //
function showLogin() {
  state.me = null;
  $("#app").hidden = true;
  $("#login").hidden = false;
  $("#login-error").textContent = "";
  $("#password").value = "";
}

function showApp() {
  $("#login").hidden = true;
  $("#app").hidden = false;
}

function paintIdentity() {
  const role = state.me.role;
  $("#who").textContent = `${state.me.full_name} (${role})`;
  $("#role-chip").textContent = role;
  $("#role-chip").className = `chip role-${role}`;
}

function allowedViews() {
  return VIEWS.filter((m) => rank(state.me.role) >= rank(m.view.minRole));
}

function paintNav() {
  const nav = $("#nav");
  nav.replaceChildren();
  for (const mod of allowedViews()) {
    nav.append(el("button", {
      type: "button",
      class: "nav-btn" + (mod.view.id === state.current ? " active" : ""),
      onclick: () => navigate(mod.view.id),
    }, mod.view.label));
  }
}

// --------------------------------------------------------------------------- //
// Router (hash based)
// --------------------------------------------------------------------------- //
let suppressHash = false;

function navigate(id) {
  if (!state.me) return;
  const allowed = allowedViews();
  let mod = BY_ID.get(id);
  if (!mod || !allowed.includes(mod)) mod = allowed[0];
  if (!mod) return;

  state.current = mod.view.id;
  if (location.hash !== `#${mod.view.id}`) {
    suppressHash = true;
    location.hash = mod.view.id;
  }
  paintNav();
  $("#page-title").textContent = mod.view.label;

  const root = $("#view-root");
  root.replaceChildren(el("p", { class: "muted" }, "Loading…"));
  Promise.resolve(mod.render(root, ctx)).catch((err) => {
    root.replaceChildren(el("p", { class: "error" }, err.message));
  });
}

window.addEventListener("hashchange", () => {
  if (suppressHash) {
    suppressHash = false;
    return;
  }
  if (state.me) navigate(location.hash.slice(1) || "dashboard");
});

// --------------------------------------------------------------------------- //
// Boot + login
// --------------------------------------------------------------------------- //
async function boot() {
  try {
    state.me = await api.get("/api/me");
    showApp();
    paintIdentity();
    const target = (location.hash || "#dashboard").slice(1);
    navigate(BY_ID.has(target) ? target : "dashboard");
  } catch (_) {
    showLogin();
  }
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await api.post("/api/login", {
      username: $("#username").value,
      password: $("#password").value,
    });
    await boot();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#demo").addEventListener("click", async () => {
  try {
    await api.post("/api/demo-login");
    await boot();
  } catch (err) {
    $("#login-error").textContent = err.message;
  }
});

$("#logout").addEventListener("click", async () => {
  try {
    await api.post("/api/logout");
  } catch (_) { /* already gone */ }
  showLogin();
});

boot();
