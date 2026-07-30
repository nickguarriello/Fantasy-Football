const PAGES = [
  ["index.html", "Home"],
  ["draft.html", "Draft Board"],
  ["assistant.html", "Draft Assistant"],
  ["startsit.html", "Start/Sit"],
  ["waivers.html", "Waivers"],
  ["matchup.html", "Matchup"],
  ["trades.html", "Trades"],
  ["playoff.html", "Playoffs"],
  ["log.html", "Log/Health"],
];

function renderNav() {
  const current = location.pathname.split("/").pop() || "index.html";
  const nav = document.createElement("header");
  nav.className = "topnav";
  nav.innerHTML =
    `<a class="brand" href="index.html">Fantasy Football</a>` +
    PAGES.map(([href, label]) =>
      `<a href="${href}" class="${href === current ? "active" : ""}">${label}</a>`
    ).join("");
  document.body.prepend(nav);
}

async function renderHealthBanner(targetEl) {
  try {
    const res = await fetch("data/health.json", { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const health = await res.json();
    const el = document.createElement("div");
    el.className = `banner ${health.overall === "ok" ? "ok" : "degraded"}`;
    el.textContent =
      health.overall === "ok"
        ? "All systems normal."
        : `Degraded: ${health.degraded_checks.join(", ")}`;
    targetEl.prepend(el);
  } catch (err) {
    const el = document.createElement("div");
    el.className = "banner error";
    el.textContent = `Could not load health.json (${err.message}). Pipeline may not have run yet.`;
    targetEl.prepend(el);
  }
}

document.addEventListener("DOMContentLoaded", renderNav);
