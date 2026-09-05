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
