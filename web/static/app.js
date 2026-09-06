async function doSearch() {
  const q = document.getElementById("q").value;
  const out = document.getElementById("searchOut");
  out.textContent = "Searching...";
  const r = await fetch("/api/search?q=" + encodeURIComponent(q));
  const d = await r.json();
  if (!d.ok) { out.textContent = d.error || "not found"; return; }
  out.innerHTML = "<b>" + d.slug + "</b> (" + d.relic + ", " + d.rarity + ")<br>" +
    "<a href='" + d.market + "' target='_blank'>market</a> " +
    "90d: " + d.p90 + " / 48h: " + d.p48 +
    (d.also_drops && d.also_drops.length ? "<br><span>Also: " + d.also_drops.join(", ") + "</span>" : "") +
    "<br><span>source: " + d.source + "</span>";
}
async function boardToggle() {
  const cur = document.getElementById("boardBtn").textContent;
  await fetch("/api/board/" + (cur === "Start" ? "start" : "stop"), {method: "POST"});
  loadBoard();
}
async function loadSets() {
  await fetch("/api/sets");
  pollSets();
}
async function pollSets() {
  const r = await fetch("/api/sets/status");
  const d = await r.json();
  if (d.ducats != null) window._ducats = d.ducats;
  const prog = document.getElementById("setsProg");
  const wrap = document.getElementById("setsProgWrap");
  const pct = d.total ? Math.round(100 * d.done / d.total) : 0;
  if (d.state === "working") {
    document.getElementById("setsBtn").disabled = true;
    wrap.style.display = "block";
    document.getElementById("setsBar").style.width = pct + "%";
    document.getElementById("setsCurrent").textContent =
      d.step + (d.total ? " (" + d.done + "/" + d.total + ", " + pct + "%)" : "...");
    prog.textContent = "Pricing... " + pct + "%";
    setTimeout(pollSets, 1500);
  } else if (d.state === "done") {
    document.getElementById("setsBtn").disabled = false;
    wrap.style.display = "none";
    prog.textContent = d.step + (d.updated ? ". Updated " + d.updated + "." : "");
    renderSets(d.report, d.listed);
  } else if (d.state === "error") {
    document.getElementById("setsBtn").disabled = false;
    wrap.style.display = "none";
    prog.textContent = "Error: " + d.error;
  } else {
    wrap.style.display = "none";
    prog.textContent = "Not priced yet.";
  }
}
function renderSets(rep, listed) {
  const out = document.getElementById("setsOut");
  const acts = (rep.actions || []).map((x, i) => {
    const price = Math.floor(x.unit);
    const btn = "<button id='act" + i + "' onclick=\"listPart('act" + i + "', '" +
      x.item + "', " + price + ", " + x.qty + ")\">List at " + price + "p</button>";
    return "<tr" + (x.hold ? " style='background:#2d2a17;'" : "") + "><td>" + x.item + "</td><td>" +
      x.kind + "</td><td>x" + x.qty + "</td><td>" + x.unit + "p</td><td>" + x.value +
      "p</td><td>" + (x.note || "") + "</td><td>" + btn + "</td></tr>";
  }).join("");
  let note;
  if (listed && listed.mode === "token") {
    note = "<div class='muted'>Checked " + listed.name + "'s listings. " +
      (rep.hidden_listed || 0) + " owned copies already listed, hidden below." +
      (listed.stale ? " Listing check is stale." : "") + "</div>";
  } else if (listed && listed.mode === "token-expired") {
    note = "<div class='muted'>Market login expired. Paste a fresh JWT into web/.env (WFM_JWT=...) and rerun.</div>";
  } else {
    note = "<div class='muted'>Already-listed check is off. Paste your JWT into web/.env as WFM_JWT to enable it.</div>";
  }
  out.innerHTML = note +
    "<h3>Best to sell, most valuable first (highlighted = keep one back, set pays more)</h3><table><thead><tr><th>Item</th><th>Kind</th><th>List qty</th><th>Each</th><th>Value</th><th>Note</th><th></th></tr></thead><tbody>" +
    (acts || "<tr><td colspan='7' class='muted'>None.</td></tr>") + "</tbody></table>";
}
async function listPart(bid, part, price, count, rank) {
  if (!confirm("List " + count + "x " + part + " at " + price + "p each?")) return;
  const btn = document.getElementById(bid);
  btn.disabled = true;
  btn.textContent = "Listing...";
  const payload = {slug: part, price: price, quantity: count};
  if (rank !== undefined) payload.rank = rank;
  const r = await fetch("/api/orders/sell", {method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload)});
  const d = await r.json();
  btn.textContent = d.ok ? "Listed" : "Failed";
  if (!d.ok) { btn.disabled = false; alert("Order failed: " + d.error); }
}
async function loadFlips() {
  await fetch("/api/baro/flips?hours=" + document.getElementById("flipHours").value);
  pollFlips();
}
async function pollFlips() {
  const r = await fetch("/api/baro/flips/status");
  const d = await r.json();
  const out = document.getElementById("flipOut");
  if (d.state === "working") {
    out.innerHTML = "<div class='muted'>Pricing primed mods...</div>";
    setTimeout(pollFlips, 2000);
  } else if (d.state === "done") {
    renderFlips(d.report);
  } else if (d.state === "error") {
    out.innerHTML = "<div class='muted'>Error: " + d.error + "</div>";
  }
}
function renderFlips(rep) {
  const out = document.getElementById("flipOut");
  const head = "<div class='muted'>" +
    ((rep.active ? "Baro is here until " + (rep.expiry || "?") + ". " : "Baro is away. Showing last stock. ") +
    (rep.ducats_balance != null ? "You hold " + rep.ducats_balance + " ducats. " : "") +
    "Targets are unranked copies.</div>");
  const body = (rep.rows || []).map((x, i) => {
    if (x.skip) return "<tr><td>" + x.item + "</td><td colspan='6' class='muted'>" + x.reason + "</td></tr>";
    const have = (x.listed || []).map(o => o.qty + "x at " + o.price + "p").join(", ");
    const note = x.ppd + "p per ducat, base " + x.baseline + "p, ceiling " + x.ceiling + "p" +
      (have ? "<br>Listed: " + have : "") +
      (x.fast_repeater ? ", repeats fast" : "") +
      (x.crashed_now ? ", crashed this week, wait to list" : "") +
      "<br>" + x.reason;
    const defq = x.owned > 0 ? x.owned : x.buy;
    let ctl;
    if (x.listed_at_target) {
      const n = (x.listed || []).filter(o => o.price === x.target)
        .map(o => o.qty).reduce((a, b) => a + b, 0);
      ctl = "<span class='muted'>Listed x" + n + " at " + x.target + "p</span>";
    } else {
      ctl = "<input id='flipq" + i + "' type='number' min='1' value='" + defq +
        "' style='width:64px; font-size:16px; padding:6px; border-radius:8px; background:#111; color:#eee; border:1px solid #555;'>" +
        " <button id='flipb" + i + "' onclick=\"listPart('flipb" + i + "', '" + x.slug + "', " +
        x.target + ", parseInt(document.getElementById('flipq" + i + "').value), 0)\">List at " +
        x.target + "p</button>";
    }
    return "<tr><td>" + x.item + "</td><td>x" + x.owned + "</td><td>" + x.ducats + "d</td><td>" + x.target +
      "p</td><td>x" + x.buy + "</td><td>" + ctl + "</td><td class='muted'>" + note + "</td></tr>";
  }).join("");
  out.innerHTML = head +
    "<h3>Flip plan, richest first</h3><table><thead><tr><th>Mod</th><th>Own</th><th>Cost</th><th>List at</th><th>Buy</th><th></th><th>Why</th></tr></thead><tbody>" +
    (body || "<tr><td colspan='7' class='muted'>Nothing this visit.</td></tr>") + "</tbody></table>";
}
async function loadBaro() {
  const r = await fetch("/api/baro");
  const d = await r.json();
  const box = document.getElementById("baroBox");
  if (!d.primed || !d.primed.length) {
    box.textContent = "Trader feed unavailable right now.";
    return;
  }
  const when = d.active ? "here until " + (d.expiry || "?") + " at " + (d.location || "?")
    : "back after " + (d.activation || "?");
  const have = window._ducats != null ? "You hold " + window._ducats + " ducats. " : "";
  box.innerHTML = have + "Baro is " + when + ". Primed mods:<br>" +
    d.primed.map(p => p.item + " " + p.ducats + "d").join(", ") +
    (d.stale ? "<br><span>Feed is stale.</span>" : "");
}
async function saveSnap() {
  document.getElementById("snapOut").textContent = "Saving...";
  const r = await fetch("/api/snapshots/save", {method: "POST"});
  const d = await r.json();
  document.getElementById("snapOut").textContent = d.ok ? "Saved " + d.file + "." : "Error: " + d.error;
}
async function diffSnaps() {
  document.getElementById("snapOut").textContent = "Diffing...";
  const l = await (await fetch("/api/snapshots/list")).json();
  const s = l.snaps || [];
  if (s.length < 2) { document.getElementById("snapOut").textContent = "Need two snapshots first."; return; }
  const r = await fetch("/api/snapshots/diff?a=" + s[1].file + "&b=" + s[0].file);
  const d = await r.json();
  if (!d.ok) { document.getElementById("snapOut").textContent = "Error: " + d.error; return; }
  const x = d.diff;
  document.getElementById("snapOut").innerHTML =
    "Plat " + x.plat_from + " to " + x.plat_to + " (" + x.plat_delta + "). " +
    "Cracked value " + x.cracked_value + "p. Sold est " + x.sold_est + "p. Relic cost " + x.relic_cost + "p at market sell." +
    "<br>Relics out: " + x.relics_out.map(e => e.relic + " x" + e.n).join(", ") +
    "<br>Parts in: " + x.parts_in.map(e => e.part + " x" + e.n + " (" + e.value + "p)").join(", ") +
    "<br>Parts out: " + x.parts_out.map(e => e.part + " x" + e.n + " (" + e.value + "p)").join(", ") +
    "<br><span>Relic cost is opportunity cost. Bought and farmed relics look the same in the dump.</span>";
}
const BOARD_WORK = ["loading reward table", "pricing gold parts", "checking sell orders"];
async function loadBoard() {
  const mp = document.getElementById("minPart").value;
  const mf = document.getElementById("minProfit").value;
  let d;
  try {
    const r = await fetch("/api/board?min_part=" + mp + "&min_profit=" + mf);
    d = await r.json();
  } catch (e) {
    document.getElementById("boardMeta").textContent =
      "Server stopped. Relaunch Relic Tools from the Start Menu.";
    document.getElementById("boardProg").style.display = "none";
    document.getElementById("boardBtn").textContent = "Start";
    return;
  }
  const c = d.cycle || {done: 0, total: 0, round: 0, phase: "idle", step: 0, steps: 2, current: "", qualified: 0};
  const pct = c.total ? Math.round(100 * c.done / c.total) : 0;
  const deals = d.fallback ? d.rows.length + " near-misses" : d.shown + " deals";
  let state;
  if (!d.running) state = "Stopped. ";
  else if (c.phase === "resting between passes") state = "Resting between passes. ";
  else state = "Scanning, pass " + c.round + ". ";
  document.getElementById("boardMeta").textContent =
    state + deals + ". Updated " + (d.updated || "never") + ".";
  const working = d.running && BOARD_WORK.includes(c.phase);
  const prog = document.getElementById("boardProg");
  prog.style.display = working ? "block" : "none";
  if (working) {
    document.getElementById("boardBar").style.width = pct + "%";
    document.getElementById("boardCurrent").textContent =
      "Step " + (c.step || 1) + " of " + (c.steps || 2) + ": " + c.phase +
      (c.current ? ", " + c.current : "") + " (" + pct + "%)";
  }
  document.getElementById("boardDebug").textContent =
    "Order feed: " + d.ws + " / market calls: " + d.market.total +
    " / pass progress: " + c.done + "/" + c.total + " (" + c.qualified + " qualify)";
  document.getElementById("boardLog").innerHTML =
    (d.activity || []).slice().reverse().map(a => "<div>" + a + "</div>").join("");
  const tb = document.getElementById("boardRows");
  document.getElementById("boardBtn").textContent = d.running ? "Stop" : "Start";
  if (!d.rows.length) {
    tb.innerHTML = "<tr><td colspan='6' class='muted'>No deals tracked yet. Start the scanner and give it a pass.</td></tr>";
  } else {
    tb.innerHTML = (d.fallback ? "<tr class='tierhead'><td colspan='6'>Nothing over the bar right now. Closest 3:</td></tr>" : "") +
    d.rows.map(x =>
      "<tr><td><a href='" + x.relic_link + "' target='_blank'>" + x.relic + "</a></td>" +
      "<td>" + x.relic_price + "p</td>" +
      "<td>x" + x.qty + "</td>" +
      "<td><a href='" + x.part_link + "' target='_blank'>" + x.part + "</a></td>" +
      "<td>" + x.part_price + "p</td><td>" + x.profit_hr + "</td></tr>").join("");
  }
  document.getElementById("alerts").innerHTML = d.alerts.slice().reverse().map(a => "<div>" + a + "</div>").join("");
}
async function quitApp() {
  if (!confirm("Quit Relic Tools? This stops the scanner and the server.")) return;
  try { await fetch("/api/quit", {method: "POST"}); } catch (e) {}
  window.close();
}
async function tileToggle() {
  const cur = document.getElementById("tileBtn").textContent;
  await fetch("/api/tile/" + (cur === "Start" ? "start" : "stop"), {method: "POST"});
  tileRefresh();
}
async function tileRefresh() {
  const r = await fetch("/api/tile");
  const d = await r.json();
  document.getElementById("tileBtn").textContent = d.running ? "Stop" : "Start";
  document.getElementById("tileState").textContent = d.running ? "running" : "";
}
async function invStatus() {
  const min = document.getElementById("tierMin").value;
  const r = await fetch("/api/inventory/status?min=" + min);
  const d = await r.json();
  const age = document.getElementById("dumpAge");
  if (d.dump && d.dump.exists) {
    age.textContent = "AlecaFrame dump updated " + d.dump.age + " (" + d.dump.mtime + ")";
  } else {
    age.textContent = "AlecaFrame dump not found.";
  }
  return d;
}
async function loadInv() {
  await fetch("/api/inventory");
  pollInv();
}
let invCache = null;
function tierTable(title, groups, showRef) {
  if (!groups.length) return "<h3>" + title + "</h3><div class='muted'>Nothing at this tier right now.</div>";
  return "<h3>" + title + "</h3><table><thead><tr><th>Relic</th>" +
    (showRef ? "<th>Refinement</th>" : "") +
    "<th>Count</th><th>Gold part</th><th>48h</th></tr></thead><tbody>" +
    groups.map(g =>
      "<tr class='tierhead'><td colspan='" + (showRef ? 5 : 4) + "'>" + title + " " + g.bucket +
      "p: " + g.relics + "x relics (" + g.types + " types)</td></tr>" +
      g.rows.map(x => "<tr><td>" + x.relic + "</td>" +
        (showRef ? "<td>" + x.ref + "</td>" : "") +
        "<td>x" + x.count + "</td><td>" + x.part + "</td><td>" + x.price + "p" +
        (x.down ? " <b>&lt;&lt; dropping</b>" : "") + "</td></tr>").join("")).join("") +
    "</tbody></table>";
}
function renderTiers() {
  if (!invCache || invCache.state !== "done") return;
  document.getElementById("invTiers").innerHTML =
    tierTable("Worth upgrading", invCache.upgrading, true) +
    tierTable("Worth opening", invCache.opening, false);
}
async function pollInv() {
  const d = await invStatus();
  const prog = document.getElementById("invProg");
  if (d.state === "working") {
    prog.textContent = d.step + (d.total ? " (" + d.done + "/" + d.total + ")" : "...");
    setTimeout(pollInv, 1000);
  } else if (d.state === "done") {
    invCache = d;
    prog.textContent = "Found " + d.types + " relic types in the local dump. Found " + d.count +
      " total relics." + (d.updated ? " Updated " + d.updated + "." : "");
    renderTiers();
  } else if (d.state === "error") {
    prog.textContent = "Error: " + d.error;
  } else {
    prog.textContent = "Not loaded yet.";
  }
}
loadBoard();
setInterval(async () => {
  await loadBoard();
}, 3000);
invStatus();
tileRefresh();
loadBaro();
loadFlips();
