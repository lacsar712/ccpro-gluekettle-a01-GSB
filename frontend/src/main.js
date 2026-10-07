import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };
const MIN_PEAK = 90;
const MIN_GRAVITY = 1.02;
const MAX_GRAVITY = 1.08;

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(data.detail || "请求失败"), { status: res.status });
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  view: location.hash === "#/gravity" ? "gravity" : "board",
  me: null,
  board: null,
  picked: null,
  peak: "96",
  gravityKettleId: null,
  readings: [],
  form: { slotNo: "1", gravity: "1.05", sampledAt: "", sampler: "" },
  err: "",
  username: "admin",
  password: "123456",
};

window.addEventListener("hashchange", () => {
  state.view = location.hash === "#/gravity" ? "gravity" : "board";
  state.err = "";
  if (state.view === "gravity") loadGravity();
  render();
});

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function refresh() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
  render();
}

async function loadGravity() {
  if (!state.board) return;
  if (state.gravityKettleId == null) state.gravityKettleId = state.board.kettles[0]?.id ?? null;
  if (state.gravityKettleId == null) {
    state.readings = [];
    return;
  }
  const data = await api(`/api/kettles/${state.gravityKettleId}/gravity`);
  state.readings = data.readings;
  render();
}

function topbar(active) {
  return el(`<nav class="topbar">
    <a class="brand" href="#/board">骨巷熬胶坊</a>
    <div class="navlinks">
      <a href="#/board" class="${active === "board" ? "active" : ""}">锅位作业台</a>
      <a href="#/gravity" class="${active === "gravity" ? "active" : ""}">比重计</a>
    </div>
    <span class="who">${esc(state.me?.username || "")}（${state.me?.role === "admin" ? "管理员" : "操作工"}）
      <button id="logout" class="linkbtn">退出</button></span>
  </nav>`);
}

function gateLine(k) {
  const peakOk = k.latestPeakC != null && k.latestPeakC >= MIN_PEAK;
  const peakText = peakOk
    ? `峰值 ${k.latestPeakC}℃ 达标`
    : k.latestPeakC == null
      ? "尚无峰值"
      : `峰值 ${k.latestPeakC}℃ 不足 90℃`;
  const gravityText = k.gravityOk
    ? `比重合格（槽位 ${k.qualifyingSlotNo}）`
    : k.gravityCount > 0
      ? `有 ${k.gravityCount} 条读数但均不在 ${MIN_GRAVITY.toFixed(2)}–${MAX_GRAVITY.toFixed(2)}`
      : "无有效比重读数";
  return `<p class="gate">
      <span class="${peakOk ? "ok" : "no"}">● ${peakText}</span>
      <span class="${k.gravityOk ? "ok" : "no"}">● ${gravityText}</span>
    </p>`;
}

function renderBoard(box) {
  box.append(el(`<p class="sub">${esc(state.board.alley)} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃ 且有合格比重读数</p>`));
  const row = el(`<div class="row"></div>`);
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}"><strong>${esc(k.code)}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  box.append(row);
  const d = el(`<section class="drawer"></section>`);
  if (state.picked) {
    d.innerHTML = `<h3>${esc(state.picked.code)} · ${LABELS[state.picked.status]}</h3>
      <p>最近峰值：${state.picked.latestPeakC ?? "无"} ℃ · 煮胶 ${state.picked.cookCount} 次</p>
      ${gateLine(state.picked)}
      <input id="peak" value="${esc(state.peak)}" />
      <button id="log">登记峰值</button>
      <div class="statusbtns">
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn" class="primary">已出胶</button>
      </div>
      <p class="hint">两套门槛都过才能改「已出胶」；比重读数请去顶部「比重计」页登记。</p>`;
    d.querySelector("#log").onclick = async () => {
      state.err = "";
      state.peak = d.querySelector("#peak").value;
      try {
        state.picked = await api(`/api/kettles/${state.picked.id}/cooks`, {
          method: "POST",
          body: JSON.stringify({ peakTempC: Number(state.peak) }),
        });
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    d.querySelectorAll("[data-s]").forEach((b) => {
      b.onclick = async () => {
        state.err = "";
        try {
          state.picked = await api(`/api/kettles/${state.picked.id}/status`, {
            method: "POST",
            body: JSON.stringify({ status: b.dataset.s }),
          });
          await refresh();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
    });
  }
  box.append(d);
}

function renderGravity(box) {
  box.append(el(`<p class="sub">按锅筛选比重读数；操作工可新建，作废仅管理员。合格区间 ${MIN_GRAVITY.toFixed(2)}–${MAX_GRAVITY.toFixed(2)}（含）。</p>`));
  const tabs = el(`<div class="row ktabs"></div>`);
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="ktab ${k.id === state.gravityKettleId ? "on" : ""}">${esc(k.code)}</button>`);
    btn.onclick = async () => {
      state.gravityKettleId = k.id;
      state.err = "";
      await loadGravity();
    };
    tabs.append(btn);
  });
  box.append(tabs);

  const gk = state.board.kettles.find((k) => k.id === state.gravityKettleId);
  if (!gk) return;

  const grid = el(`<section class="gravity-grid"></section>`);

  const form = el(`<form class="card gform" autocomplete="off">
    <h3>为 ${esc(gk.code)} 新建读数</h3>
    <label>槽位号（从 1 起）
      <input name="slotNo" type="number" min="1" step="1" value="${esc(state.form.slotNo)}" />
    </label>
    <label>比重
      <input name="gravity" type="number" step="0.001" min="0" value="${esc(state.form.gravity)}" />
    </label>
    <label>取样时刻（可空，默认现在）
      <input name="sampledAt" type="datetime-local" value="${esc(state.form.sampledAt)}" />
    </label>
    <label>取样人（可空，默认本人）
      <input name="sampler" value="${esc(state.form.sampler)}" placeholder="${esc(state.me?.username || "")}" />
    </label>
    <button class="primary">提交读数</button>
  </form>`);
  form.onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    const v = (name) => form.querySelector(`[name=${name}]`).value;
    const payload = {
      slotNo: Number(v("slotNo")),
      gravity: Number(v("gravity")),
    };
    if (v("sampledAt")) payload.sampledAt = new Date(v("sampledAt")).toISOString();
    if (v("sampler")) payload.sampler = v("sampler");
    state.form = { slotNo: v("slotNo"), gravity: v("gravity"), sampledAt: v("sampledAt"), sampler: v("sampler") };
    try {
      await api(`/api/kettles/${state.gravityKettleId}/gravity`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      await loadGravity();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  grid.append(form);

  const list = el(`<div class="card glist"><h3>${esc(gk.code)} 的读数</h3><div class="rows"></div></div>`);
  const rows = list.querySelector(".rows");
  if (state.readings.length === 0) {
    rows.append(el(`<p class="hint">该锅还没有任何比重读数。无读数不能出胶。</p>`));
  }
  state.readings.forEach((r) => {
    const voided = Boolean(r.voidedAt);
    const badge = voided
      ? `<span class="badge void">已作废</span>`
      : r.inBand
        ? `<span class="badge ok">合格</span>`
        : `<span class="badge out">出带</span>`;
    const rowEl = el(`<div class="grow ${voided ? "is-void" : ""}">
      <div class="grow-main">
        <strong>槽位 ${r.slotNo}</strong> · 比重 ${r.gravity} ${badge}
      </div>
      <div class="grow-meta">取样时刻 ${fmtTime(r.sampledAt)} · 取样人 ${esc(r.sampler) || "—"} · 作废时刻 ${fmtTime(r.voidedAt)}</div>
      <div class="grow-act"></div>
    </div>`);
    if (!voided && state.me?.role === "admin") {
      const vb = el(`<button class="danger">作废</button>`);
      vb.onclick = async () => {
        if (!confirm(`确认作废 ${esc(gk.code)} 槽位 ${r.slotNo} 的读数？作废后不可用于放行。`)) return;
        state.err = "";
        try {
          await api(`/api/kettles/${state.gravityKettleId}/gravity/${r.id}/void`, { method: "POST" });
          await loadGravity();
        } catch (ex) {
          state.err = ex.message;
          render();
        }
      };
      rowEl.querySelector(".grow-act").append(vb);
    }
    rows.append(rowEl);
  });
  grid.append(list);
  box.append(grid);
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    const box = el(`<div class="wrap">
      <h1>骨巷熬胶坊</h1>
      <p>一排熬锅作业台，原生页面，无前端框架。</p>
      <form autocomplete="off">
        <label>用户名
          <input name="u" autocomplete="off" value="${esc(state.username)}" />
        </label>
        <label>密码
          <input name="p" type="password" autocomplete="off" value="${esc(state.password)}" />
        </label>
        <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
        <button>登录</button>
      </form>
      <p class="err">${esc(state.err)}</p>
    </div>`);
    box.querySelector("form").onsubmit = async (e) => {
      e.preventDefault();
      state.err = "";
      try {
        const data = await api("/api/auth/login", {
          method: "POST",
          body: JSON.stringify({
            username: box.querySelector("[name=u]").value,
            password: box.querySelector("[name=p]").value,
          }),
        });
        localStorage.setItem(TOKEN_KEY, data.access_token);
        state.me = data.user;
        state.ready = true;
        await api("/api/board").then((b) => (state.board = b));
        state.picked = state.board.kettles[0];
        if (state.view === "gravity") await loadGravity();
        render();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
    app.append(box);
    return;
  }
  if (!state.board) {
    app.append(el(`<div class="wrap">${esc(state.err || "装载锅位…")}</div>`));
    return;
  }
  const shell = el(`<div></div>`);
  const bar = topbar(state.view);
  bar.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    location.hash = "";
    location.reload();
  };
  shell.append(bar);
  const box = el(`<div class="wrap"></div>`);
  if (state.view === "gravity") renderGravity(box);
  else renderBoard(box);
  if (state.err) box.append(el(`<p class="err">${esc(state.err)}</p>`));
  shell.append(box);
  app.append(shell);
}

async function boot() {
  try {
    state.me = await api("/api/auth/me");
    state.board = await api("/api/board");
    state.picked = state.board.kettles[0];
    if (state.view === "gravity") await loadGravity();
  } catch (e) {
    if (e.status === 401) {
      state.ready = false;
      state.err = "登录已过期，请重新登录";
    } else {
      state.err = e.message;
    }
  }
  render();
}

if (state.ready) {
  boot();
} else {
  render();
}
