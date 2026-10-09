// Browser checks for the page and the Jira mapping.
//
//   npm i --no-save playwright && python3 tests/make_jira_fixture.py
//   node tests/browser_check.mjs
//
// Uses the Chromium Playwright finds (PLAYWRIGHT_BROWSERS_PATH), or CHROMIUM.
import { chromium } from "playwright";
import { execFileSync } from "node:child_process";
import { readFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TMP = mkdtempSync(join(tmpdir(), "portfolio-check-"));
const SHOTS = process.env.SHOTS || null;
const fx = n => JSON.parse(readFileSync(join(ROOT, "tests/fixtures", n), "utf8"));
const py = (...a) => execFileSync("python3", [join(ROOT, "build_portfolio.py"), ...a], { encoding: "utf8" });

let failed = 0;
const check = (ok, msg) => { console.log((ok ? "  ok   " : "  FAIL ") + msg); if (!ok) failed++; };

py("--write-data", join(TMP, "sample.json"));
const sample = JSON.parse(readFileSync(join(TMP, "sample.json"), "utf8")).USE_CASES;

const browser = await chromium.launch(process.env.CHROMIUM ? { executablePath: process.env.CHROMIUM } : {});
async function open(file) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(pathToFileURL(file).href);
  await page.waitForSelector("#srcbar b");
  return { page, errors };
}
async function visitAll(page) {
  for (const t of ["thinking", "intake", "portfolio", "status", "jira", "aifirst"]) {
    await page.click("#tabbtn-" + t);
    await page.waitForTimeout(60);
  }
}

console.log("sample page");
{
  const { page, errors } = await open(join(ROOT, "ai-use-case-dashboard.html"));
  await visitAll(page);
  check(errors.length === 0, "no script errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  check((await page.textContent("#srcbar")).includes("Sample data"), "source strip says sample");

  console.log("mapper, clean fixture round-trips to the sample");
  const out = await page.evaluate(f => JiraMapper.map(f, JIRA_MAP), fx("jira_clean.json"));
  check(out.report.shown === sample.length && out.report.total === sample.length, "all " + sample.length + " issues placed");
  const KEYS = ["id", "name", "func", "stage", "owner", "sponsor", "wsjf", "est", "size", "impact", "metric",
                "dataReady", "baseline", "risk", "waitingOn", "opened", "lastUpdate", "target", "next", "closed"];
  let diffs = [];
  for (const s of sample) {
    const m = out.useCases.find(u => u.id === s.id);
    if (!m) { diffs.push(s.id + " missing"); continue; }
    for (const k of KEYS) {
      const a = JSON.stringify(s[k] ?? null), b = JSON.stringify(m[k] ?? null);
      if (a !== b) diffs.push(s.id + "." + k + ": sample " + a + " vs jira " + b);
    }
  }
  check(diffs.length === 0, "every field matches" + (diffs.length ? "\n         " + diffs.join("\n         ") : ""));
  check(out.report.problems.filter(p => p.sev !== "info").length === 0,
        "no warnings on clean data" + JSON.stringify(out.report.problems.map(p => p.msg)));

  console.log("mapper, messy fixture");
  const m = await page.evaluate(f => JiraMapper.map(f, JIRA_MAP), fx("jira_messy.json"));
  const keys = m.report.problems.map(p => p.key);
  check(m.report.shown === sample.length - 1 && m.report.skipped[0].key === "AI-002", "unmapped status is left off, and named");
  check(keys.includes("status:ready for uat"), "unmapped status reported as an error");
  check(keys.includes("ambiguous:size"), "duplicate Story Points field reported");
  check(m.report.fields.find(f => f.target === "size").id === "customfield_10016", "duplicate resolved to the filled-in field");
  check(keys.includes("value:impact:Customer experience"), "unknown select option reported");
  check(keys.includes("notarget"), "missing target date reported");
  check(m.useCases.find(u => u.id === "AI-005").targetDerived === true, "missing target is derived, and marked");
  check(m.useCases.find(u => u.id === "AI-003").est === 1200, "\"$1,200\" read as 1200");

  console.log("loading a file on the page");
  await page.click("#tabbtn-jira");
  await page.setInputFiles("#datacheck-body input[type=file]", join(ROOT, "tests/fixtures/jira_messy.json"));
  await page.waitForFunction(() => document.querySelector("#srcbar").textContent.includes("Live from Jira"));
  check((await page.textContent("#srcbar")).includes("15 of 16"), "source strip counts what made the board");
  check((await page.locator(".dcprob li").count()) >= 4, "data check lists the problems");
  await visitAll(page);
  check(errors.length === 0, "no script errors after loading" + (errors.length ? ": " + errors.join(" | ") : ""));
  await page.close();
}

console.log("page built from a Jira file");
{
  const built = join(TMP, "built.html");
  const log = py("--jira-file", join(ROOT, "tests/fixtures/jira_messy.json"), "-o", built);
  check(/status not mapped to a stage: 'Ready for UAT'/.test(log), "build pre-check names the unmapped status");
  const html = readFileSync(built, "utf8");
  check(!html.includes("emailAddress") && !html.includes("accountId") && !html.includes("avatarUrls"),
        "no account ids, emails or avatars embedded");
  check(!html.includes("Problem statement for"), "descriptions left out while includeText is off");
  const { page, errors } = await open(built);
  await visitAll(page);
  check(errors.length === 0, "no script errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  check((await page.textContent("#srcbar")).includes("15 of 16"), "source strip counts what made the board");
  await page.click("#tabbtn-portfolio");
  check((await page.textContent("#trend-value")).includes("No history yet"), "no sample trend shown next to real data");
  await page.click("#tabbtn-status");
  check((await page.textContent("#rag-parts")).includes("Not measured"), "value is unrated, not green");
  check((await page.locator("#status-week-select option").count()) === 1, "no sample reports in the history");
  await page.click("#tabbtn-jira");
  await page.click("#jira-list tbody tr:nth-child(4)");
  check((await page.textContent("#jira-issue .jtitle")).length > 0, "clicking a row opens that issue");
  if (SHOTS) {
    await page.click("#tabbtn-jira");
    await page.screenshot({ path: join(SHOTS, "jira-live.png"), fullPage: true });
    await page.click("#tabbtn-portfolio");
    await page.screenshot({ path: join(SHOTS, "portfolio-live.png"), fullPage: true });
  }
  await page.close();
}

await browser.close();
console.log(failed ? "\n" + failed + " check(s) failed" : "\nall checks passed");
process.exit(failed ? 1 : 0);
