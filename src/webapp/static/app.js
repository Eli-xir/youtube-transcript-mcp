/* YouTube Transcript Studio -- vanilla JS, no build step. */
"use strict";

const $ = (id) => document.getElementById(id);
const state = { videoId: null, payload: null, segs: [], player: null, playerReady: false, timer: null };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fmtHMS(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${m}:${String(s).padStart(2, "0")}`;
}

function setStatus(msg, cls = "") {
  const el = $("global-status");
  el.textContent = msg || "";
  el.className = "status " + cls;
}

async function api(path, opts) {
  const r = await fetch(path, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(body.message || r.statusText), { payload: body });
  return body;
}

/* ---------------------------------------------------------------- player */

let ytApiReady = !!(window.YT && window.YT.Player);

window.onYouTubeIframeAPIReady = function () {
  ytApiReady = true;
  if (state.pendingVideoId) createPlayer(state.pendingVideoId, state.pendingStart || 0);
};

function createPlayer(videoId, startAt = 0) {
  state.playerReady = false;
  if (state.player) {
    try { state.player.destroy(); } catch { /* already gone */ }
    state.player = null;
  }
  const wrap = document.querySelector(".player-wrap");
  const host = document.createElement("div");
  host.id = "player";
  wrap.innerHTML = "";
  wrap.appendChild(host);
  state.player = new YT.Player("player", {
    height: "100%", width: "100%",
    videoId,
    playerVars: { rel: 0, modestbranding: 1, start: Math.floor(startAt),
                  autoplay: startAt > 0 ? 1 : 0 },
    events: { onReady: () => { state.playerReady = true; } },
  });
}

function ensureVideoLoaded(videoId, startAt = 0) {
  state.pendingVideoId = videoId;
  state.pendingStart = startAt;
  if (!ytApiReady) return; // created later by onYouTubeIframeAPIReady
  if (state.playerReady && state.player?.loadVideoById) {
    try { state.player.loadVideoById(videoId, startAt); return; } catch { /* recreate */ }
  }
  createPlayer(videoId, startAt);
}

function seekTo(seconds) {
  if (state.playerReady && state.player?.seekTo) {
    try {
      state.player.seekTo(Math.max(0, seconds), true);
      state.player.playVideo();
      return;
    } catch { /* fall through to recreate */ }
  }
  // API not responsive (e.g. restricted webview): rebuild the embed at the timestamp
  if (state.videoId) createPlayer(state.videoId, seconds);
}

/* ------------------------------------------------------------- loading */

$("load-form").addEventListener("submit", (e) => { e.preventDefault(); loadVideo(); });

async function loadVideo() {
  const url = $("url-input").value.trim();
  if (!url) return;
  $("load-btn").disabled = true;
  $("main").classList.remove("hidden");
  setStatus("Loading metadata…", "busy");
  clearTranscriptView();
  try {
    const meta = await api("/api/metadata", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
    state.videoId = meta.video_id;
    renderMeta(meta);
    ensureVideoLoaded(meta.video_id);

    let payload = null;
    try {
      setStatus("Checking cache…", "busy");
      payload = await api(`/api/transcript?video=${encodeURIComponent(meta.video_id)}`);
      setStatus("cached transcript", "");
    } catch {
      setStatus("Fetching transcript (captions-first; whisper may take a while)…", "busy");
      payload = await api("/api/transcribe", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
    }
    state.payload = payload;
    renderTranscript(payload);
    loadChapters();
    setStatus("");
  } catch (err) {
    const hint = err.payload?.hint ? ` — ${esc(err.payload.hint)}` : "";
    setStatus(err.payload?.error ? `${err.payload.error}: ${esc(err.message)}` : esc(err.message), "error");
    if (!state.payload) {
      $("transcript").innerHTML =
        `<div class="empty">${esc(err.message)}${hint}</div>`;
    }
  } finally {
    $("load-btn").disabled = false;
  }
}

function renderMeta(meta) {
  $("meta-title").textContent = meta.title || meta.video_id;
  $("meta-channel").textContent = meta.channel || "unknown channel";
  $("meta-dur").textContent = fmtHMS(meta.duration || 0);
}

function renderBadges(p) {
  const b = [];
  const src = p.transcript_source || "";
  b.push(`<span class="badge src-${esc(src)}">${esc(src || "?")}</span>`);
  b.push(`<span class="badge">${esc(p.language || "?")}</span>`);
  if (p.model) b.push(`<span class="badge">${esc(p.model)}</span>`);
  if (p.cache_hit) b.push(`<span class="badge cache-hit">cache hit</span>`);
  b.push(`<span class="badge">${p.segment_count ?? (p.segments || []).length} segs</span>`);
  if (p.elapsed_s != null) b.push(`<span class="badge">${p.elapsed_s}s</span>`);
  $("meta-badges").innerHTML = b.join("");
}

/* ------------------------------------------------------------ transcript */

function clearTranscriptView() {
  state.payload = null; state.segs = [];
  $("transcript").innerHTML = `<div class="empty">Loading…</div>`;
  $("search-results").classList.add("hidden");
  $("summary-out").classList.add("hidden");
  $("chapters").innerHTML = `<div class="none">Loading…</div>`;
}

function renderTranscript(p) {
  renderBadges(p);
  const wrap = document.createElement("div");
  state.segs = [];
  for (const s of p.segments || []) {
    const row = document.createElement("div");
    row.className = "seg";
    const t = document.createElement("time");
    t.textContent = fmtHMS(s.start);
    const tx = document.createElement("span");
    tx.className = "text";
    tx.textContent = s.text;
    row.append(t, tx);
    row.addEventListener("click", () => seekTo(s.start));
    wrap.append(row);
    state.segs.push({ start: s.start, end: s.end, el: row, textEl: tx, raw: s.text });
  }
  const tr = $("transcript");
  tr.innerHTML = "";
  tr.append(wrap);
  if (!state.segs.length) {
    tr.innerHTML = `<div class="empty">Transcript is empty.</div>`;
  }
  startFollow();
}

/* follow playback: highlight the active segment */
function startFollow() {
  if (state.timer) clearInterval(state.timer);
  state.timer = setInterval(() => {
    if (!state.playerReady || !state.segs.length || !$("follow-toggle").checked) return;
    let t;
    try { t = state.player.getCurrentTime(); } catch { return; }
    if (t == null) return;
    const i = activeIndex(t);
    state.segs.forEach((s, j) => s.el.classList.toggle("active", j === i));
    if (i >= 0) {
      const el = state.segs[i].el;
      const box = $("transcript");
      const inView = el.offsetTop >= box.scrollTop && el.offsetTop <= box.scrollTop + box.clientHeight - 60;
      if (!inView) box.scrollTop = el.offsetTop - box.clientHeight / 3;
      markActiveChapter(state.segs[i].start);
    }
  }, 400);
}

function activeIndex(t) {
  let lo = 0, hi = state.segs.length - 1, ans = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (state.segs[mid].start <= t) { ans = mid; lo = mid + 1; } else { hi = mid - 1; }
  }
  return ans;
}

/* --------------------------------------------------------------- search */

$("search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch();
});

async function doSearch() {
  const q = $("search-input").value.trim();
  if (!q || !state.videoId) return;
  state.segs.forEach((s) => { s.el.classList.remove("hit"); s.textEl.textContent = s.raw; });
  const box = $("search-results");
  box.classList.remove("hidden");
  box.innerHTML = `<div class="none">Searching…</div>`;
  try {
    const r = await api(`/api/search?video=${encodeURIComponent(state.videoId)}&q=${encodeURIComponent(q)}&context=1&max=20`);
    if (!r.results.length) {
      box.innerHTML = `<div class="none">No matches for “${esc(q)}”.</div>`;
      return;
    }
    box.innerHTML = "";
    const ql = q.toLowerCase();
    for (const res of r.results) {
      const div = document.createElement("div");
      div.className = "result";
      const time = document.createElement("time");
      time.textContent = fmtHMS(res.start);
      const span = document.createElement("span");
      span.textContent = res.matched.join(" … ");
      div.append(time, span);
      div.addEventListener("click", () => { seekTo(res.start); jumpToSeg(res.start); });
      box.append(div);
      // highlight matching segments in the transcript
      for (const s of state.segs) {
        if (s.start >= res.start - 0.01 && s.start <= res.end + 0.01) {
          s.el.classList.add("hit");
          if (!/[A-Z]/.test(q.replace(/[^A-Za-z]/g, "")) || q === q.toLowerCase()) {
            const low = s.raw.toLowerCase();
            const at = low.indexOf(ql);
            if (at >= 0) {
              s.textEl.innerHTML =
                esc(s.raw.slice(0, at)) + "<mark>" + esc(s.raw.slice(at, at + q.length)) + "</mark>" +
                esc(s.raw.slice(at + q.length));
            }
          }
        }
      }
    }
    jumpToSeg(r.results[0].start);
  } catch (err) {
    box.innerHTML = `<div class="none">${esc(err.message)}</div>`;
  }
}

function jumpToSeg(seconds) {
  const i = activeIndex(seconds + 0.01);
  if (i >= 0) {
    const box = $("transcript");
    box.scrollTop = state.segs[i].el.offsetTop - box.clientHeight / 3;
    state.segs[i].el.classList.add("hit");
  }
}

/* -------------------------------------------------------------- chapters */

async function loadChapters() {
  if (!state.videoId) return;
  $("chapters").innerHTML = `<div class="none">Loading…</div>`;
  try {
    const r = await api(`/api/chapters?video=${encodeURIComponent(state.videoId)}&ai=1`);
    const el = $("chapters");
    el.innerHTML = "";
    if (!r.chapters.length) {
      el.innerHTML = `<div class="none">No chapters found.</div>`;
      return;
    }
    for (const c of r.chapters) {
      const div = document.createElement("div");
      div.className = "chapter";
      const t = document.createElement("time");
      t.textContent = fmtHMS(c.start);
      const span = document.createElement("span");
      span.textContent = c.title + (c.source === "heuristic" ? " (auto)" : "");
      div.append(t, span);
      div.addEventListener("click", () => seekTo(c.start));
      el.append(div);
    }
  } catch (err) {
    $("chapters").innerHTML = `<div class="none">${esc(err.message)}</div>`;
  }
}

function markActiveChapter(seconds) {
  const kids = [...$("chapters").children];
  let active = -1;
  kids.forEach((k, i) => {
    const parts = k.querySelector("time").textContent.split(":").map(Number);
    const s = parts.length === 3 ? parts[0] * 3600 + parts[1] * 60 + parts[2]
                                 : parts[0] * 60 + parts[1];
    if (s <= seconds + 0.5) active = i;
  });
  kids.forEach((k, i) => k.classList.toggle("active", i === active));
}

/* --------------------------------------------------------------- summary */

$("summary-btn").addEventListener("click", async () => {
  if (!state.videoId) return;
  const btn = $("summary-btn");
  const out = $("summary-out");
  btn.disabled = true;
  out.classList.remove("hidden");
  out.textContent = "Generating…";
  try {
    const r = await api("/api/summary", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ video: state.videoId, style: $("summary-style").value }),
    });
    out.textContent = r.text;
  } catch (err) {
    out.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});
