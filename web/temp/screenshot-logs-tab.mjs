import { chromium } from "@playwright/test";
import { resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));

const TOPIC_ID = "0e71f9af-23df-460b-ac9a-6f3356c23020";

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const page = await context.newPage();

// Intercept API calls to avoid CORS issues in headless mode
await page.route("http://localhost:8000/**", async (route) => {
  const url = route.request().url();
  
  if (url.includes(`/topics/${TOPIC_ID}`) && !url.includes("/chat") && !url.includes("/sources") && !url.includes("/document") && !url.includes("/graph")) {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: TOPIC_ID,
        user_id: "test-user-local",
        title: "Test Topic - Llull UI",
        context_summary: null,
        created_at: "2026-06-02T19:48:27.875766",
        updated_at: "2026-06-02T19:48:27.875766",
      }),
    });
  } else if (url.includes("/topics") && !url.includes(TOPIC_ID)) {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify([{
        id: TOPIC_ID,
        user_id: "test-user-local",
        title: "Test Topic - Llull UI",
        context_summary: null,
        created_at: "2026-06-02T19:48:27.875766",
        updated_at: "2026-06-02T19:48:27.875766",
      }]),
    });
  } else {
    await route.continue();
  }
});

// Navigate directly to the topic
await page.goto(`http://localhost:3001/topics/${TOPIC_ID}`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1500);

// Wait for tabs to appear
try {
  await page.waitForSelector('[role="tab"]', { timeout: 8000 });
} catch {
  console.log("Tabs not found");
  await page.screenshot({ path: resolve(__dirname, "debug.png"), fullPage: false });
  await browser.close();
  process.exit(1);
}

const tabCount = await page.locator('[role="tab"]').count();
console.log(`Found ${tabCount} tabs`);

// Take screenshot of topic view with Chat tab active
await page.screenshot({ path: resolve(__dirname, "topic-view.png"), fullPage: false });
console.log("Took topic-view screenshot");

// Click the Logs tab
const logsTab = page.locator('[role="tab"]:has-text("Logs")');
await logsTab.click();
await page.waitForTimeout(500);

// Take initial screenshot (empty state)
await page.screenshot({ path: resolve(__dirname, "logs-tab-empty.png"), fullPage: false });
console.log("Took logs-tab-empty screenshot");

// Inject some console logs and trigger fetch requests that will be intercepted
await page.evaluate(async () => {
  console.log("App initialized successfully");
  console.log("Topic loaded: Test Topic - Llull UI");
  console.warn("Warning: API response time exceeded 500ms");
  console.error("Error: Failed to parse response from /api/graph");
  console.log("User navigated to Logs tab");
  // These fetches will be intercepted and logged
  fetch("http://localhost:8000/topics").then(() => {}).catch(() => {});
  await new Promise((r) => setTimeout(r, 100));
  fetch("http://localhost:8000/topics/nonexistent-id").then(() => {}).catch(() => {});
});

await page.waitForTimeout(1200);

// Take final screenshot with entries
await page.screenshot({ path: resolve(__dirname, "logs-tab.png"), fullPage: false });
console.log("Took logs-tab screenshot with entries");

await browser.close();
console.log("Done");
