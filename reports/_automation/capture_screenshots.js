const fs = require("fs");
const path = require("path");

const { chromium } = require("playwright-core");

const FRONTEND_BASE = "http://127.0.0.1:5173";
const OUT_DIR = "C:/condocharge-platform/reports/screenshots";
const CHROME_EXE = "C:/Users/Alessandro/AppData/Local/ms-playwright/chromium-1223/chrome-win64/chrome.exe";
const DESKTOP_VIEWPORT = { width: 1440, height: 1200 };
const MOBILE_VIEWPORT = { width: 390, height: 844 };

function out(filename) {
  return path.join(OUT_DIR, filename);
}

async function screenshot(page, filename) {
  await page.screenshot({ path: out(filename) });
}

async function waitForAppShell(page) {
  await page.locator(".app-shell").first().waitFor({ state: "visible", timeout: 15000 });
  await page.locator(".app-content").first().waitFor({ state: "visible", timeout: 15000 });
}

async function login(page, { username, password, condominium }) {
  await page.goto(`${FRONTEND_BASE}/login`, { waitUntil: "domcontentloaded" });
  await page.locator('label:has-text("Nome utente") input').fill(username);
  await page.locator('label:has-text("Password") input').fill(password);
  if (condominium) {
    await page.locator('label:has-text("Condominio") input').fill(condominium);
  }
  await page.getByRole("button", { name: "Accedi" }).click();
  await waitForAppShell(page);
}

async function gotoAuthed(page, pathname, waitText) {
  await page.goto(`${FRONTEND_BASE}${pathname}`, { waitUntil: "domcontentloaded" });
  await waitForAppShell(page);
  if (waitText) {
    await page.locator(`.page-title:has-text("${waitText}")`).first().waitFor({ state: "visible", timeout: 15000 });
  }
}

async function openMenu(page) {
  const toggle = page.locator(".nav-toggle").first();
  await toggle.waitFor({ state: "attached", timeout: 15000 });
  if (await toggle.isVisible()) {
    await toggle.click();
    await page.locator("nav.nav--open").first().waitFor({ state: "visible", timeout: 15000 });
    return;
  }
  await page.locator("nav.nav").first().waitFor({ state: "visible", timeout: 15000 });
}

async function closeMenu(page) {
  const nav = page.locator("nav.nav--open").first();
  if (await nav.count()) {
    await page.locator(".app-content").first().click({ force: true });
  }
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const browser = await chromium.launch({ executablePath: CHROME_EXE, headless: true });
  const desktopContext = await browser.newContext({ viewport: DESKTOP_VIEWPORT, deviceScaleFactor: 1 });
  const desktopPage = await desktopContext.newPage();

  await login(desktopPage, {
    username: "resident_real",
    password: "password123",
  });

  await openMenu(desktopPage);
  await screenshot(desktopPage, "resident_real-00-menu-desktop.png");
  await closeMenu(desktopPage);

  await gotoAuthed(desktopPage, "/resident/consumi", "I miei consumi");
  await desktopPage.waitForTimeout(700);
  await screenshot(desktopPage, "resident_real-01-dashboard-desktop.png");

  await gotoAuthed(desktopPage, "/resident/stato-colonnine", "Stato colonnine");
  await desktopPage.locator("text=CHARGING").first().waitFor({ state: "visible", timeout: 30000 });
  await desktopPage.locator(".pill.is-ok").first().waitFor({ state: "visible", timeout: 30000 });
  await desktopPage.waitForTimeout(300);
  await screenshot(desktopPage, "resident_real-02-stations-desktop.png");

  await gotoAuthed(desktopPage, "/resident/ricariche", "Le mie ricariche");
  await desktopPage.waitForTimeout(700);
  await screenshot(desktopPage, "resident_real-03-charging-history-desktop.png");

  await gotoAuthed(desktopPage, "/resident/profilo", "Profilo");
  await desktopPage.waitForTimeout(700);
  await screenshot(desktopPage, "resident_real-04-profile-desktop.png");

  const mobileContext = await browser.newContext({ viewport: MOBILE_VIEWPORT, deviceScaleFactor: 2 });
  const mobilePage = await mobileContext.newPage();

  await login(mobilePage, {
    username: "resident_real",
    password: "password123",
  });

  await openMenu(mobilePage);
  await screenshot(mobilePage, "resident_real-05-menu-mobile.png");
  await closeMenu(mobilePage);

  await gotoAuthed(mobilePage, "/resident/consumi", "I miei consumi");
  await mobilePage.waitForTimeout(700);
  await screenshot(mobilePage, "resident_real-06-dashboard-mobile.png");

  await gotoAuthed(mobilePage, "/resident/stato-colonnine", "Stato colonnine");
  await mobilePage.locator("text=CHARGING").first().waitFor({ state: "visible", timeout: 30000 });
  await mobilePage.locator(".pill.is-ok").first().waitFor({ state: "visible", timeout: 30000 });
  await mobilePage.waitForTimeout(300);
  await screenshot(mobilePage, "resident_real-07-stations-mobile.png");

  await gotoAuthed(mobilePage, "/resident/ricariche", "Le mie ricariche");
  await mobilePage.waitForTimeout(700);
  await screenshot(mobilePage, "resident_real-08-charging-history-mobile.png");

  await gotoAuthed(mobilePage, "/resident/profilo", "Profilo");
  await mobilePage.waitForTimeout(700);
  await screenshot(mobilePage, "resident_real-09-profile-mobile.png");

  await browser.close();
  process.stdout.write(`Screenshots generated in ${OUT_DIR}\n`);
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack ? err.stack : err) + "\n");
  process.exit(1);
});
