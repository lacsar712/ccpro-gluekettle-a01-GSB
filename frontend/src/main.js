import "./style.css";

const TOKEN_KEY = "gluekettle_token";
const USER_KEY = "gluekettle_user";
const LABELS = { cold: "冷锅", boiling: "熬煮中", drawn: "已出胶" };
const ROLE_LABELS = { admin: "管理员", worker: "操作工" };
const SG_MIN = 1.02;
const SG_MAX = 1.08;

async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const t = localStorage.getItem(TOKEN_KEY);
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(path, { ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || "请求失败");
  return data;
}

const app = document.getElementById("app");
const state = {
  ready: Boolean(localStorage.getItem(TOKEN_KEY)),
  user: JSON.parse(localStorage.getItem(USER_KEY) || "null"),
  view: "board",
  board: null,
  picked: null,
  peak: "96",
  err: "",
  username: "admin",
  password: "123456",
  readings: null,
  filterKettleId: "",
  form: { kettleId: "", slotNo: "1", gravity: "1.050", sampledAt: "" },
};

function el(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function fmtTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("zh-CN", { hour12: false });
}

async function refresh() {
  state.board = await api("/api/board");
  if (state.picked) {
    state.picked = state.board.kettles.find((k) => k.id === state.picked.id) || state.board.kettles[0];
  }
  render();
}

async function loadReadings() {
  const q = state.filterKettleId ? `?kettleId=${state.filterKettleId}` : "";
  const data = await api(`/api/readings${q}`);
  state.readings = data.readings;
}

function render() {
  app.innerHTML = "";
  if (!state.ready) {
    renderLogin();
    return;
  }
  const page = el(`<div>
    <nav class="topnav">
      <span class="brand">骨巷熬胶坊</span>
      <button data-view="board" class="${state.view === "board" ? "on" : ""}">锅位作业台</button>
      <button data-view="density" class="${state.view === "density" ? "on" : ""}">比重计</button>
      <span class="who">${state.user?.username ?? ""}（${ROLE_LABELS[state.user?.role] ?? state.user?.role ?? ""}）</span>
      <button id="logout" class="link">退出</button>
    </nav>
    <div id="view"></div>
  </div>`);
  page.querySelectorAll("[data-view]").forEach((b) => {
    b.onclick = async () => {
      if (state.view === b.dataset.view) return;
      state.view = b.dataset.view;
      state.err = "";
      if (state.view === "density") {
        try {
          await loadReadings();
        } catch (ex) {
          state.err = ex.message;
        }
      }
      render();
    };
  });
  page.querySelector("#logout").onclick = () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    location.reload();
  };
  app.append(page);
  const view = page.querySelector("#view");
  if (state.view === "board") renderBoard(view);
  else renderDensity(view);
}

function renderLogin() {
  const box = el(`<div class="wrap">
    <h1>骨巷熬胶坊</h1>
    <p>一排熬锅作业台，原生页面，无前端框架。</p>
    <form autocomplete="off">
      <label>用户名
        <input name="u" autocomplete="off" value="${state.username}" />
      </label>
      <label>密码
        <input name="p" type="password" autocomplete="off" value="${state.password}" />
      </label>
      <p class="hint">已预填 admin / 123456，另有 worker / 123456</p>
      <button>登录</button>
    </form>
    <p class="err">${state.err}</p>
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
      localStorage.setItem(USER_KEY, JSON.stringify(data.user));
      state.user = data.user;
      state.ready = true;
      await refresh();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  app.append(box);
}

function renderBoard(view) {
  if (!state.board) {
    view.append(el(`<div class="wrap">${state.err || "装载锅位…"}</div>`));
    return;
  }
  const box = el(`<div class="wrap">
    <h1>${state.board.workshop}</h1>
    <p>${state.board.alley} · 点锅登记峰值；出胶须最近峰值 ≥ 90℃ 且有合格比重读数（${SG_MIN.toFixed(2)}–${SG_MAX.toFixed(2)}，比重计页登记）</p>
    <div class="row"></div>
    <section class="drawer"></section>
    <p class="err">${state.err}</p>
  </div>`);
  const row = box.querySelector(".row");
  state.board.kettles.forEach((k) => {
    const btn = el(`<button class="kettle ${k.status}"><strong>${k.code}</strong><span>${LABELS[k.status]}</span></button>`);
    btn.onclick = () => {
      state.picked = k;
      render();
    };
    row.append(btn);
  });
  if (state.picked) {
    const d = box.querySelector(".drawer");
    d.innerHTML = `<h3>${state.picked.code} · ${LABELS[state.picked.status]}</h3>
      <p>最近峰值：${state.picked.latestPeakC ?? "无"} ℃ · ${state.picked.cookCount} 次</p>
      <p>比重读数：未作废 ${state.picked.readingCount} 条 · ${
        state.picked.hasQualifiedReading
          ? '<span class="ok">已有合格读数，可放行出胶</span>'
          : '<span class="bad">无合格读数，请到「比重计」页登记</span>'
      }</p>
      <input id="peak" value="${state.peak}" />
      <button id="log">登记峰值</button>
      <div>
        <button data-s="cold">冷锅</button>
        <button data-s="boiling">熬煮中</button>
        <button data-s="drawn">已出胶</button>
      </div>`;
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
  view.append(box);
}

function readingStatus(r) {
  if (r.voidedAt) return '<span class="badge void">已作废</span>';
  if (r.qualified) return '<span class="badge ok">合格</span>';
  return '<span class="badge bad">超范围</span>';
}

function renderDensity(view) {
  if (!state.board) {
    view.append(el(`<div class="wrap">${state.err || "装载锅位…"}</div>`));
    return;
  }
  const kettles = state.board.kettles;
  const filterOpts = ['<option value="">全部锅</option>']
    .concat(
      kettles.map(
        (k) =>
          `<option value="${k.id}" ${String(k.id) === String(state.filterKettleId) ? "selected" : ""}>${k.code}</option>`
      )
    )
    .join("");
  const defaultKettle = state.form.kettleId || (state.picked && state.picked.id) || (kettles[0] && kettles[0].id) || "";
  const kettleOpts = kettles
    .map(
      (k) =>
        `<option value="${k.id}" ${String(k.id) === String(defaultKettle) ? "selected" : ""}>${k.code}</option>`
    )
    .join("");
  const rows = (state.readings || [])
    .map((r) => {
      const canVoid = state.user?.role === "admin" && !r.voidedAt;
      return `<tr>
        <td>${r.kettleCode}</td>
        <td>${r.slotNo}</td>
        <td>${Number(r.gravity).toFixed(3)}</td>
        <td>${fmtTime(r.sampledAt)}</td>
        <td>${r.sampledBy}</td>
        <td>${readingStatus(r)}</td>
        <td>${fmtTime(r.voidedAt)}</td>
        <td>${canVoid ? `<button data-void="${r.id}">作废</button>` : "—"}</td>
      </tr>`;
    })
    .join("");
  const box = el(`<div class="wrap">
    <h1>比重计</h1>
    <p class="hint">出胶放行须存在未作废且比重在 ${SG_MIN.toFixed(2)}–${SG_MAX.toFixed(2)}（含）的读数；同锅未作废槽位号唯一；作废仅管理员。</p>
    <div class="bar">
      <label>按锅筛
        <select id="filter">${filterOpts}</select>
      </label>
    </div>
    <form id="new-reading" class="bar" autocomplete="off">
      <label>锅码
        <select name="kettle">${kettleOpts}</select>
      </label>
      <label>槽位号
        <input name="slot" type="number" min="1" step="1" value="${state.form.slotNo}" />
      </label>
      <label>比重
        <input name="gravity" type="number" step="0.001" value="${state.form.gravity}" />
      </label>
      <label>取样时刻
        <input name="at" type="datetime-local" value="${state.form.sampledAt || nowLocal()}" />
      </label>
      <button>登记读数</button>
    </form>
    <table class="readings">
      <thead>
        <tr><th>锅码</th><th>槽位号</th><th>比重</th><th>取样时刻</th><th>取样人</th><th>状态</th><th>作废时刻</th><th>操作</th></tr>
      </thead>
      <tbody>${rows || '<tr><td colspan="8" class="hint">暂无读数</td></tr>'}</tbody>
    </table>
    <p class="err">${state.err}</p>
  </div>`);
  box.querySelector("#filter").onchange = async (e) => {
    state.filterKettleId = e.target.value;
    state.err = "";
    try {
      await loadReadings();
    } catch (ex) {
      state.err = ex.message;
    }
    render();
  };
  box.querySelector("#new-reading").onsubmit = async (e) => {
    e.preventDefault();
    state.err = "";
    const f = e.target;
    state.form = {
      kettleId: f.querySelector("[name=kettle]").value,
      slotNo: f.querySelector("[name=slot]").value,
      gravity: f.querySelector("[name=gravity]").value,
      sampledAt: f.querySelector("[name=at]").value,
    };
    try {
      await api("/api/readings", {
        method: "POST",
        body: JSON.stringify({
          kettleId: Number(state.form.kettleId),
          slotNo: Number(state.form.slotNo),
          gravity: Number(state.form.gravity),
          sampledAt: state.form.sampledAt || undefined,
        }),
      });
      state.form.slotNo = String(Number(state.form.slotNo) + 1);
      await loadReadings();
      await refresh();
    } catch (ex) {
      state.err = ex.message;
      render();
    }
  };
  box.querySelectorAll("[data-void]").forEach((b) => {
    b.onclick = async () => {
      state.err = "";
      try {
        await api(`/api/readings/${b.dataset.void}/void`, { method: "POST" });
        await loadReadings();
        await refresh();
      } catch (ex) {
        state.err = ex.message;
        render();
      }
    };
  });
  view.append(box);
}

async function boot() {
  if (!state.ready) {
    render();
    return;
  }
  try {
    state.user = await api("/api/auth/me");
    localStorage.setItem(USER_KEY, JSON.stringify(state.user));
    await refresh();
  } catch (e) {
    state.err = e.message;
    render();
  }
}

boot();
