/* Drives the built page in headless Chromium and checks that it works.
 *
 *   npm i -D playwright   (or set PW to a global install's path)
 *   node browser_check.js
 *
 * Builds a page from the sample data plus one hostile ticket, then exercises
 * every control. Exits non-zero on the first failure.
 */
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require(process.env.PW || "playwright");

const here = __dirname;
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "jp-check-"));
const today = new Date().toISOString().slice(0, 10);

// Sample issues plus a ticket whose summary tries to inject markup.
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
const out = path.join(tmp, "page.html");
execFileSync("python3", [path.join(here, "jira_portfolio.py"), "--config", path.join(tmp, "cfg.json"),
  "--from-json", path.join(tmp, "raw.json"), "--out", out], { env: { PATH: process.env.PATH } });
const URL0 = "file://" + out;

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
  const text = sel => page.locator(sel).first().innerText();

  try {
    await page.goto(URL0);
    ok(await page.locator("#groups .group").count() > 3, "command center renders groups");
    ok(await page.evaluate(() => window.__pwned) === undefined, "hostile summary did not execute");
    ok((await page.locator("text=window.__pwned=1").count()) > 0 || (await page.content()).includes("onerror"),
      "hostile summary shown as text");

    // filter by health from a KPI tile
    await page.locator(".kpi[title=\"Filter to Off track\"]").click();
    ok((await hash()).includes("health=red"), "KPI tile sets the health filter in the URL");
    const offTrack = await page.locator("#groups .item").count();
    await page.locator(".kpi[title=\"Filter to Off track\"]").click();
    ok((await page.locator("#groups .item").count()) > offTrack, "clicking the tile again clears it");

    // check chip narrows the list
    await page.locator(".chip", { hasText: "No owner" }).click();
    const chipN = Number(await page.locator(".chip", { hasText: "No owner" }).locator(".c").innerText());
    ok(await page.locator("#groups .item").count() === chipN, "check chip filters to its own count");
    await page.locator(".chip", { hasText: "No owner" }).click();

    // group by owner: email + jira bulk link
    await page.locator("[data-group=owner]").click();
    const chris = page.locator(".group", { hasText: "Chris Tan" }).first();
    const mail = await chris.locator("a", { hasText: "Email owner" }).getAttribute("href");
    ok(mail.startsWith("mailto:chris.tan@example.com?subject="), "email owner is addressed to them");
    ok(decodeURIComponent(mail).includes("AI-41"), "email body lists their items");
    const bulk = await chris.locator("a", { hasText: "in Jira" }).getAttribute("href");
    ok(bulk.startsWith("https://jira.example.com/issues/?jql=") && decodeURIComponent(bulk).includes("key in (AI-4,AI-41)"),
      "bulk link opens their issues in the Jira navigator");

    // nudge persists across reload and can be hidden
    const before = await page.locator("#groups .item").count();
    await page.locator("#groups .item button", { hasText: "Mark nudged" }).first().click();
    await page.reload();
    ok(await page.locator("#groups .item button", { hasText: /^✓ Nudged/ }).count() === 1, "nudge survives a reload");
    await page.locator("#f-nudged").check();
    ok(await page.locator("#groups .item").count() === before - 1, "hide nudged removes it");
    await page.locator("#f-nudged").uncheck();

    // search + owner filter + reset
    await page.locator("[data-tab=issues]").click();
    const all = await page.locator("#tbody tr").count();
    await page.locator("#f-q").fill("underwriter");
    await page.waitForTimeout(250);
    ok(await page.locator("#tbody tr").count() === 1, "search filters the table");
    await page.locator("#f-reset").click();
    ok(await page.locator("#tbody tr").count() === all, "reset restores every row");
    await page.selectOption("#f-owner", "Priya Nair");
    ok((await page.locator("#tbody tr").allInnerTexts()).every(t => t.includes("Priya Nair")), "owner filter");
    await page.selectOption("#f-owner", "");

    // sorting
    await page.locator("th button", { hasText: "Due" }).click();
    ok(await page.locator("th[aria-sort=ascending]", { hasText: "Due" }).count() === 1, "sort ascending marked for screen readers");
    const dues = await page.locator("#tbody tr td:nth-child(8)").allInnerTexts();
    const dated = dues.filter(d => d !== "—").map(d => Date.parse(d));
    ok(dated.every((d, i) => i === 0 || d >= dated[i - 1]), "due dates ascend");
    ok(dues.slice(dated.length).every(d => d === "—"), "undated rows sort last");
    await page.locator("th button", { hasText: "Due" }).click();
    ok((await hash()).includes("dir=desc"), "second click sorts descending");

    // include done
    const openRows = await page.locator("#tbody tr").count();
    await page.locator("#f-done").check();
    ok(await page.locator("#tbody tr").count() > openRows, "include done adds done issues");
    await page.locator("#f-done").uncheck();

    // drawer
    await page.locator("#tbody tr", { hasText: "AI-12" }).locator("td").nth(2).click();
    ok(await page.locator("#drawer").evaluate(d => d.open), "row opens the detail drawer");
    ok(await page.locator("#d-open").getAttribute("href") === "https://jira.example.com/browse/AI-12", "drawer links to the ticket");
    await page.locator("#d-body .linkbtn", { hasText: "AI-1" }).click();
    ok((await text("#d-key")) === "AI-1", "parent link navigates the drawer");
    await page.keyboard.press("Escape");
    ok(!(await page.locator("#drawer").evaluate(d => d.open)), "Escape closes the drawer");

    // keys open Jira in a new tab, not the drawer
    const a = page.locator("#tbody a.key").first();
    ok(await a.getAttribute("target") === "_blank" && (await a.getAttribute("rel")).includes("noopener"), "key links open safely in a new tab");

    // csv
    const [dl] = await Promise.all([page.waitForEvent("download"), page.locator("#btn-csv").click()]);
    const csv = fs.readFileSync(await dl.path(), "utf8");
    ok(csv.split("\r\n").length - 1 === await page.locator("#tbody tr").count(), "CSV has one line per visible row");
    ok(csv.includes("'=HYPERLINK"), "CSV neutralizes formula injection");

    // deep link restores the view
    await page.goto(URL0 + "#tab=issues&owner=Lena+Ortiz&sort=key");
    await page.reload();
    ok(await page.locator("#f-owner").inputValue() === "Lena Ortiz" && (await page.locator("#tbody tr").count()) === 2,
      "a shared URL restores tab, filter and sort");

    // capabilities
    await page.goto(URL0 + "#tab=caps");
    await page.reload();
    ok((await text(".cap .hbadge")).includes("Off track"), "worst capability is listed first");
    ok(await page.locator(".cap").count() === Number(await text("#n-caps")) + 1, "capability tab count matches cards (+ unlinked)");

    // method + mobile
    await page.locator("[data-tab=method]").click();
    ok((await text("#method")).includes("past its due date"), "scoring rules are explained");
    await page.setViewportSize({ width: 375, height: 800 });
    await page.locator("[data-tab=command]").click();
    ok(await page.evaluate(() => document.documentElement.scrollWidth <= 375), "no horizontal scroll on a phone");

    ok(errors.length === 0, "no console errors" + (errors.length ? ": " + errors.join(" | ") : ""));
    console.log("\n" + passed + " checks passed");
  } catch (e) {
    if (!process.exitCode) { console.error(e); process.exitCode = 1; }
  } finally {
    await browser.close();
  }
})();
