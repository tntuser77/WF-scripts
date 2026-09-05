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
async function loadSets() {
  await fetch("/api/sets");
  pollSets();
}
async function pollSets() {
  const r = await fetch("/api/sets/status");
  const d = await r.json();
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
    renderSets(d.report);
  } else if (d.state === "error") {
    document.getElementById("setsBtn").disabled = false;
    wrap.style.display = "none";
    prog.textContent = "Error: " + d.error;
  } else {
    wrap.style.display = "none";
    prog.textContent = "Not priced yet.";
  }
}
function renderSets(rep) {
  const out = document.getElementById("setsOut");
  const near = (rep.near || []).map(x =>
    "<tr><td><a href='" + x.set_link + "' target='_blank'>" + x.set + "</a> (" +
    x.have + "/" + x.need + ")</td><td>" + x.sell_now + "p</td><td>" +
    (x.set_sell != null ? x.set_sell + "p" : "?") + "</td><td>" +
    (x.marginal != null ? x.marginal + "p" : "?") + "</td><td>" +
    (x.buy != null ? x.buy + "p" : "?") + "</td><td>" +
    (x.source ? x.source.relic + " " + x.source.exp_runs + " runs, own " + x.source.owned : "?") +
    "</td><td>" + x.verdict + "</td></tr>").join("");
  const comp = (rep.complete || []).map(x =>
    "<tr><td><a href='" + x.set_link + "' target='_blank'>" + x.set + "</a></td><td>" +
    x.set_sell + "p</td></tr>").join("");
  const sell = (rep.sell_rank || []).slice(0, 20).map(x =>
    "<tr" + (x.hold ? " style='background:#2d2a17;'" : "") + "><td>" + x.part + "</td><td>x" +
    x.count + "</td><td>" + x.p48 + "p</td><td>" + x.value + "p</td><td>" +
    (x.hold ? "hold, finishes " + x.set : x.set || "") + "</td></tr>").join("");
  out.innerHTML =
    "<h3>One piece short (" + (rep.near || []).length + ")</h3><table><thead><tr><th>Set</th><th>Sell parts</th><th>Set sells</th><th>Missing worth</th><th>Buy missing</th><th>Farm</th><th>Call</th></tr></thead><tbody>" +
    (near || "<tr><td colspan='7' class='muted'>None.</td></tr>") + "</tbody></table>" +
    "<h3>Complete, ready to list (" + (rep.complete || []).length + ")</h3><table><tbody>" +
    (comp || "<tr><td class='muted'>None.</td></tr>") + "</tbody></table>" +
    "<h3>Best parts to sell (highlighted = hold, finishes a set)</h3><table><thead><tr><th>Part</th><th>Count</th><th>48h</th><th>Value</th><th>Set</th></tr></thead><tbody>" + sell + "</tbody></table>";
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
loadBoard();
}
async function loadBoard() {
  const mp = document.getElementById("minPart").value;
  const mf = document.getElementById("minProfit").value;
  const r = await fetch("/api/board?min_part=" + mp + "&min_profit=" + mf);
  const d = await r.json();
  const c = d.cycle || {done: 0, total: 0, round: 0, phase: "idle", current: "", qualified: 0};
  const pct = c.total ? Math.round(100 * c.done / c.total) : 0;
  document.getElementById("boardMeta").textContent =
    (d.running ? "Scanning. pass " + c.round + " (" + c.done + "/" + c.total + " relics, " +
      c.qualified + " qualify). " : "Stopped. ") +
    "Showing " + d.shown + " of " + d.tracked + " tracked. " +
    "Updated: " + (d.updated || "never") + " / order feed: " + d.ws +
    " / market calls: " + d.market.total;
  const prog = document.getElementById("boardProg");
  prog.style.display = d.running ? "block" : "none";
  document.getElementById("boardBar").style.width = pct + "%";
  document.getElementById("boardCurrent").textContent =
    c.phase + (c.current ? ": " + c.current : "") + (c.total ? " (" + pct + "%)" : "");
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
