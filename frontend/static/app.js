/* 岸桥小车导轨拼接曲线审计 —— 前端逻辑（原生 JS，无构建步骤） */

const STORAGE_KEY = "railcurve-draft-v1";

// 默认示例：两段抛物线弧，端点与切向量均连续，各段最大曲率 2/3
const EXAMPLE = {
  max_curvature: 1.0,
  segments: [
    [[0, 0], [1, 0], [2, 1], [3, 3]],
    [[3, 3], [4, 5], [5, 6], [6, 6]],
  ],
};

const REASON_TEXT = {
  curvature_exceeded: "曲率超限",
  endpoint_mismatch: "端点断接",
  tangent_mismatch: "切向断接",
  zero_tangent: "零切向量（不可运行）",
};

const $ = (sel) => document.querySelector(sel);

let state = loadDraft() || structuredClone(EXAMPLE);

function loadDraft() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const d = JSON.parse(raw);
    if (!d || !Array.isArray(d.segments)) return null;
    if (d.segments.length < 2 || d.segments.length > 5) return null;
    return d;
  } catch {
    return null;
  }
}

function saveDraft(showMsg = true) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  if (showMsg) {
    $("#draft-info").textContent = "草稿已保存（" + new Date().toLocaleTimeString() + "）";
  }
}

function fmt(v) {
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "-";
  return Number(Number(v).toFixed(6)).toString();
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function renderEditor() {
  $("#segment-count").value = String(state.segments.length);
  $("#max-curvature").value = state.max_curvature;
  const host = $("#segments-editor");
  host.innerHTML = "";
  state.segments.forEach((seg, i) => {
    const fs = document.createElement("fieldset");
    const lg = document.createElement("legend");
    lg.textContent = `第 ${i + 1} 段`;
    fs.appendChild(lg);
    const table = document.createElement("table");
    table.className = "points";
    table.innerHTML = "<thead><tr><th>控制点</th><th>x</th><th>y</th></tr></thead>";
    const tbody = document.createElement("tbody");
    seg.forEach((pt, j) => {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>P${j}</td>` + [0, 1].map((ax) =>
        `<td><input type="number" step="1" value="${pt[ax]}" ` +
        `data-seg="${i}" data-pt="${j}" data-axis="${ax}"></td>`
      ).join("");
      tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    fs.appendChild(table);
    host.appendChild(fs);
  });
  host.querySelectorAll("input").forEach((inp) =>
    inp.addEventListener("input", (e) => {
      const el = e.target;
      const v = parseFloat(el.value);
      state.segments[+el.dataset.seg][+el.dataset.pt][+el.dataset.axis] =
        Number.isNaN(v) ? 0 : v;
    })
  );
}

function renderResult(data) {
  const box = $("#result");
  if (data.ok) {
    const rows = data.segments.map((s) =>
      `<tr><td>第 ${s.index + 1} 段</td><td>${fmt(s.max_curvature)}</td>` +
      `<td>${fmt(s.t)}</td><td>(${fmt(s.point.x)}, ${fmt(s.point.y)})</td></tr>`
    ).join("");
    box.innerHTML =
      `<div class="pass">✔ 合格：各段曲率均在限值 ${fmt(data.max_curvature_limit)} 以内，拼接连续。</div>` +
      `<table class="result"><thead><tr><th>段</th><th>最大曲率</th><th>参数 t</th><th>位置 (x, y)</th></tr></thead>` +
      `<tbody>${rows}</tbody></table>`;
  } else {
    const f = data.failure || {};
    const reason = REASON_TEXT[f.reason] || f.reason || "未知原因";
    const joint = f.adjacent_segment_index !== undefined && f.adjacent_segment_index !== null
      ? `（与第 ${f.adjacent_segment_index + 1} 段之间）` : "";
    box.innerHTML =
      `<div class="fail">✘ 不合格：${escapeHtml(reason)}</div>` +
      `<table class="result"><tbody>` +
      `<tr><th>最早问题段</th><td>第 ${(f.segment_index ?? 0) + 1} 段${joint}</td></tr>` +
      `<tr><th>曲线参数 t</th><td>${fmt(f.t)}</td></tr>` +
      `<tr><th>坐标</th><td>(${fmt(f.point && f.point.x)}, ${fmt(f.point && f.point.y)})</td></tr>` +
      `<tr><th>原因</th><td>${escapeHtml(f.message || reason)}</td></tr>` +
      `</tbody></table>`;
  }
}

async function runAudit() {
  for (const seg of state.segments) {
    for (const p of seg) {
      for (const v of p) {
        if (!Number.isInteger(v)) {
          alert("控制点坐标必须为整数，请检查草稿。");
          return;
        }
      }
    }
  }
  if (!(state.max_curvature > 0)) {
    alert("统一最大曲率必须为正数。");
    return;
  }
  const payload = {
    max_curvature: state.max_curvature,
    segments: state.segments.map((seg) => ({
      points: seg.map((p) => ({ x: p[0], y: p[1] })),
    })),
  };
  const panel = $("#result-panel");
  const box = $("#result");
  panel.hidden = false;
  box.innerHTML = "审计中…";
  try {
    const res = await fetch("/api/audit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => null);
    if (!res.ok) {
      box.innerHTML = `<div class="fail">请求被拒绝（HTTP ${res.status}）` +
        `<pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre></div>`;
      return;
    }
    renderResult(data);
  } catch (err) {
    box.innerHTML = `<div class="fail">无法连接审计服务：${escapeHtml(String(err))}</div>`;
  }
}

async function pingApi() {
  const pill = $("#api-status");
  try {
    const r = await fetch("/api/health");
    if (!r.ok) throw new Error("bad status");
    pill.textContent = "API 正常";
    pill.className = "pill ok";
  } catch {
    pill.textContent = "API 不可达";
    pill.className = "pill bad";
  }
}

$("#segment-count").addEventListener("change", (e) => {
  const n = parseInt(e.target.value, 10);
  while (state.segments.length < n) {
    const p = state.segments[state.segments.length - 1][3];
    state.segments.push([[...p], [p[0] + 1, p[1]], [p[0] + 2, p[1]], [p[0] + 3, p[1]]]);
  }
  state.segments = state.segments.slice(0, n);
  renderEditor();
});

$("#max-curvature").addEventListener("input", (e) => {
  const v = parseFloat(e.target.value);
  state.max_curvature = Number.isNaN(v) ? 0 : v;
});

$("#btn-example").addEventListener("click", () => {
  state = structuredClone(EXAMPLE);
  renderEditor();
  $("#draft-info").textContent = "已载入示例曲线。";
});

$("#btn-save").addEventListener("click", () => saveDraft(true));

$("#btn-clear").addEventListener("click", () => {
  localStorage.removeItem(STORAGE_KEY);
  $("#draft-info").textContent = "草稿已清除。";
});

$("#btn-audit").addEventListener("click", runAudit);

renderEditor();
pingApi();
