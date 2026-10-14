/* Drives the built page in headless Chromium and checks that it works.
 *
 *   npm i -D playwright   (or set PW to a global install's path)
 *   node browser_check.js
 *
 * Builds two pages in a temp folder: the sample (with its eight-week history),
 * and a page from a saved pull that carries one hostile ticket and two weekly
 * runs of real snapshot history. Then exercises every view and control.
 * Exits non-zero on the first failure.
 */
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require(process.env.PW || "playwright");

const here = __dirname;
const script = path.join(here, "jira_portfolio.py");
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "jp-check-"));
const today = new Date().toISOString().slice(0, 10);
const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString().slice(0, 10);
const run = args => execFileSync("python3", [script, ...args], { cwd: tmp, env: { PATH: process.env.PATH } });

// 1. the sample
run(["--sample", "--out", "sample.html"]);
// 2. a saved pull with a hostile ticket, run last week and again today so the history is real
const raw = JSON.parse(execFileSync("python3", ["-c",
  "import json,sys,datetime as d;sys.path.insert(0,sys.argv[1]);import jira_portfolio as j;" +
  "print(json.dumps({'issues': j.sample_issues(d.date.fromisoformat(sys.argv[2]))}))", here, today]).toString());
raw.issues.push({ key: "AI-99", fields: {
  summary: "<img src=x onerror=\"window.__pwned=1\"></script><script>window.__pwned=2</script>",
  issuetype: { name: "Epic" }, status: { name: "In Progress", statusCategory: { key: "indeterminate" } },
  assignee: { displayName: "=HYPERLINK(\"http://evil\")" }, duedate: null, updated: today + "T00:00:00.000+0000",
  parent: { key: "AI-1" }, description: "x" } });
fs.writeFileSync(path.join(tmp, "raw.json"), JSON.stringify(raw));
fs.writeFileSync(path.join(tmp, "cfg.json"), JSON.stringify({
  title: "Check", base_url: "https://jira.example.com", rag_field: "customfield_10100",
  flagged_field: "customfield_10021", owner_field: { Capability: "customfield_10300", default: "assignee" },
  required_fields: [{ field: "customfield_10200", label: "Business value", types: ["Capability"] }] }));
run(["--config", "cfg.json", "--from-json", "raw.json", "--out", "real.html", "--today", weekAgo]);
run(["--config", "cfg.json", "--from-json", "raw.json", "--out", "real.html"]);
const SAMPLE = "file://" + path.join(tmp, "sample.html");
const REAL = "file://" + path.join(tmp, "real.html");

let passed = 0;
function ok(cond, msg) {
  if (!cond) { console.error("FAIL: " + msg); process.exitCode = 1; throw new Error(msg); }
  passed++;
  console.log("ok  " + msg);
}

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1400, height: 1000 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  const hash = () => page.evaluate(() => location.hash);
  const go = async (u, h) => { await page.goto(u + (h || "")); await page.reload(); };

  try {
    // ---------- files the run should leave behind
    ok(fs.readdirSync(path.join(tmp, "jira_portfolio_history")).length === 2, "two runs leave two snapshots");
    ok(fs.readFileSync(path.join(tmp, "weekly-report-" + today + ".md"), "utf8").includes("## What changed since"),
      "weekly report written as Markdown, compared with last week");

    // ---------- overview
    await go(SAMPLE);
    ok(await page.locator("#p-overview .band .stat").count() === 6, "overview opens with the stat band");
    for (const t of ["Capability health", "Pipeline by Jira status", "Due in the next eight weeks", "What's missing",
                     "Open work by owner", "Time in current status", "Health week by week", "Completeness week by week",
                     "Epics completed per month", "Cycle time, created to done"])
      ok(await page.locator(`#p-overview section[aria-label="${t}"]`).count() === 1, "chart: " + t);
    ok(await page.locator("#p-overview .take").count() >= 10, "every chart carries a takeaway");
    // white space: what's absent is drawn, not left out
    const due = page.locator('#p-overview section[aria-label="Due in the next eight weeks"]');
    ok(await due.locator(".xl span", { hasText: "No date" }).count() === 1 && await due.locator(".cols .c-miss").count() === 1,
      "due chart has a No date column");
    ok(await due.locator(".xl span", { hasText: "Late" }).count() === 1, "due chart keeps its Late label");
    ok(await page.locator('#p-overview section[aria-label="Open work by owner"] .track .c-miss').count() === 1, "unowned work is drawn as missing");
    const missRows = page.locator('#p-overview section[aria-label="What\'s missing"] .gaprow');
    ok(await missRows.count() >= 6, "what's missing shows each field filled against empty");
    await missRows.filter({ hasText: "Due date" }).click();
    ok((await hash()).includes("tab=actions") && (await hash()).includes("check=no_due"), "a missing field drills into its actions");
    ok(await page.locator("#p-actions .item").count() === 3, "and lists exactly the undated items");
    await page.locator("#t-overview").click();
    ok((await page.locator("#head").innerText()).indexOf("null") === -1, "no stray text in the page head");
    await page.locator('#p-overview button.stat[title*="off track"]').click();
    ok((await hash()).includes("health=red"), "stat tile filters by health");
    await page.locator('#p-overview button.stat[title*="off track"]').click();
    await page.locator("#p-overview .hrow.click", { hasText: "Blocked" }).click();
    ok((await hash()).includes("tab=issues") && (await hash()).includes("status=Blocked"), "pipeline row drills into the issue list");
    await page.locator("#f-reset").click();
    await page.locator("#t-overview").click();
    await page.locator("#p-overview .caprow").first().click();
    ok(await page.locator("#drawer").evaluate(d => d.open), "capability row opens its detail");
    await page.keyboard.press("Escape");
    await page.locator("#p-overview .track span").first().hover();
    ok(await page.locator("#tip.show").count() === 1, "bars show a tooltip on hover");

    // ---------- weekly report
    await page.locator("#t-report").click();
    ok((await page.locator("h1").innerText()).startsWith("Week of"), "report is titled by week");
    ok(await page.locator("#p-report .overall").count() === 1 && await page.locator("#p-report .elem").count() === 3,
      "overall RAG and three elements");
    ok(await page.locator("#filters").isHidden(), "filters hidden on the report");
    for (const t of ["What changed since", "What didn't move", "What we need to know", "Needs a decision", "Coming up", "What's missing"])
      ok(await page.locator("#p-report .rsec h3", { hasText: t }).count() === 1, "report section: " + t);
    ok(await page.locator("#p-report .rgrp h4", { hasText: "Status moves" }).count() === 1, "week-over-week status moves listed");
    ok(await page.locator("#p-report .rgrp h4", { hasText: "Not started after" }).count() === 1, "unstarted work listed next to what changed");
    ok(await page.locator("#p-report .rgrp h4", { hasText: "No date set" }).count() === 1, "undated work listed with what's coming up");
    const weeks = await page.locator("#r-week option").count();
    ok(weeks >= 8, "earlier weeks are kept (" + weeks + ")");
    await page.selectOption("#r-week", { index: 3 });
    ok((await hash()).includes("week="), "picking an earlier week is in the URL");
    ok(await page.locator("#p-report .fcount", { hasText: "earlier week" }).count() === 1, "earlier week is labeled as such");
    await page.selectOption("#r-week", { index: 0 });
    const [md] = await Promise.all([page.waitForEvent("download"), page.locator("#p-report button", { hasText: "Download .md" }).click()]);
    ok(fs.readFileSync(await md.path(), "utf8").startsWith("# "), "report downloads as Markdown");
    await page.locator("#p-report .rgrp .linkish").first().click();
    ok(await page.locator("#drawer").evaluate(d => d.open), "report lines open the issue");
    await page.keyboard.press("Escape");

    // ---------- actions
    await page.locator("#t-actions").click();
    ok(await page.locator("#p-actions .side button").count() === 12, "check list renders as buttons, not text");
    const chip = page.locator("#p-actions .side button", { hasText: "No owner" });
    await chip.click();
    const n = Number(await chip.locator(".c").innerText());
    ok(await page.locator("#p-actions .item").count() === n, "check filters to its own count");
    await page.locator("#p-actions .side button", { hasText: "All actions" }).click();
    await page.locator("#p-actions .seg button", { hasText: "Owner" }).click();
    const chris = page.locator("#p-actions .grp", { hasText: "Chris Tan" }).first();
    const mail = await chris.locator("a", { hasText: "Email" }).getAttribute("href");
    ok(mail.startsWith("mailto:chris.tan@example.com?subject="), "email goes to the owner");
    const bulk = await chris.locator("a", { hasText: "in Jira" }).getAttribute("href");
    ok(decodeURIComponent(bulk).includes("key in (AI-4,AI-41)"), "bulk link opens their issues in Jira");
    const before = await page.locator("#p-actions .item").count();
    await page.locator("#p-actions .item button", { hasText: "Mark nudged" }).first().click();
    await page.reload();
    ok(await page.locator("#p-actions .item button", { hasText: /^✓ Nudged/ }).count() === 1, "nudge survives a reload");
    await page.locator("#f-nudged").check();
    ok(await page.locator("#p-actions .item").count() === before - 1, "hide nudged removes it");
    await page.locator("#f-nudged").uncheck();

    // ---------- capabilities
    await page.locator("#t-caps").click();
    const capRows = page.locator("#p-caps tbody tr.row:not(.child)");
    ok((await capRows.first().innerText()).includes("Off track"), "worst capability first");
    await capRows.first().locator(".tog").click();
    ok(await page.locator("#p-caps tr.child").count() > 0, "capability expands to its epics");
    ok(await page.locator("#p-caps h2", { hasText: "not linked" }).count() === 1, "unlinked epics listed separately");

    // ---------- issues
    await page.locator("#t-issues").click();
    const all = await page.locator("#p-issues tbody tr").count();
    await page.locator("#f-q").fill("underwriter");
    await page.waitForTimeout(250);
    ok(await page.locator("#p-issues tbody tr").count() === 1, "search filters");
    await page.locator("#f-reset").click();
    ok(await page.locator("#p-issues tbody tr").count() === all, "reset restores every row");
    await page.selectOption("#f-owner", "Priya Nair");
    ok((await page.locator("#p-issues tbody tr").allInnerTexts()).every(t => t.includes("Priya Nair")), "owner filter");
    await page.selectOption("#f-owner", { index: 0 });
    await page.locator("#p-issues th button", { hasText: "Due" }).click();
    ok(await page.locator('#p-issues th[aria-sort="ascending"]', { hasText: "Due" }).count() === 1, "sort state exposed to screen readers");
    const dues = (await page.locator("#p-issues tbody tr td:nth-child(8)").allInnerTexts()).map(t => t.split("\n")[0]);
    const dated = dues.filter(d => d !== "—").map(d => Date.parse(d + " 2026"));
    ok(dues.slice(dated.length).every(d => d === "—"), "undated rows sort last");
    ok(await page.locator("#p-issues tbody .miss", { hasText: "No date" }).count() === 3, "blank due dates are marked, not dashed");
    ok(await page.locator("#p-issues tbody .miss", { hasText: "No owner" }).count() === 3, "blank owners are marked");
    await page.locator("#f-done").check();
    ok(await page.locator("#p-issues tbody tr").count() > all, "include done adds done work");
    await page.locator("#f-done").uncheck();
    await page.locator("#p-issues tbody tr", { hasText: "AI-12" }).locator("td").nth(2).click();
    ok(await page.locator("#d-open").getAttribute("href") === "https://example.atlassian.net/browse/AI-12", "drawer links to the ticket");
    await page.locator("#d-body .linkish", { hasText: "AI-1 " }).click();
    ok((await page.locator("#d-key").innerText()).startsWith("AI-1 "), "parent link navigates the drawer");
    await page.keyboard.press("Escape");
    ok(!(await page.locator("#drawer").evaluate(d => d.open)), "Escape closes the drawer");

    // ---------- method
    await page.locator("#t-method").click();
    ok((await page.locator("#p-method").innerText()).includes("Overall takes the worst"), "method explains the report");

    // ---------- the real-history page: hostile input, csv, deep link
    await go(REAL);
    ok(await page.evaluate(() => window.__pwned) === undefined, "hostile summary did not execute");
    await go(REAL, "#tab=report");
    ok((await page.locator(".lede").innerText()).includes("compared with the snapshot from"), "report compares with last week's real snapshot");
    await go(REAL, "#tab=issues");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.locator("#p-issues button", { hasText: "Export CSV" }).click()]);
    const csv = fs.readFileSync(await dl.path(), "utf8");
    ok(csv.split("\r\n").length - 1 === await page.locator("#p-issues tbody tr").count(), "CSV has one line per visible row");
    ok(csv.includes("'=HYPERLINK"), "CSV neutralizes formula injection");
    await go(REAL, "#tab=issues&owner=Lena+Ortiz&sort=key");
    ok(await page.locator("#f-owner").inputValue() === "Lena Ortiz", "a shared URL restores tab, filter and sort");

    // ---------- every view at phone width, light and dark
    for (const scheme of ["light", "dark"]) {
      const p = await browser.newPage({ viewport: { width: 375, height: 800 }, colorScheme: scheme });
      p.on("pageerror", e => errors.push(e.message));
      for (const t of ["overview", "report", "actions", "caps", "issues", "method"]) {
        await p.goto(SAMPLE + "#tab=" + t); await p.reload();
        const w = await p.evaluate(() => document.documentElement.scrollWidth);
        ok(w <= 375, `no horizontal scroll on a phone: ${t} (${scheme})`);
        const txt = await p.locator("main").innerText();
        ok(!/\bnull\b|\bundefined\b|\[object /.test(txt), `no leaked null/undefined/[object] text: ${t} (${scheme})`);
      }
      await p.close();
    }

    ok(errors.length === 0, "no console errors" + (errors.length ? ": " + errors.join(" | ") : ""));
    console.log("\n" + passed + " checks passed");
  } catch (e) {
    if (!process.exitCode) { console.error(e); process.exitCode = 1; }
  } finally {
    await browser.close();
    fs.rmSync(tmp, { recursive: true, force: true });
  }
})();
