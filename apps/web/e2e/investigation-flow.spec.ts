import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "";
const LEAD = process.env.E2E_LEAD ?? "lead@demo.example.org";
const REVIEWER = process.env.E2E_REVIEWER ?? "reviewer@demo.example.org";

test.skip(!PASSWORD, "set E2E_PASSWORD (the BM_SEED_PASSWORD used for seed-demo)");

/** Visible control by exact label (Cache Components keeps previous pages mounted but hidden). */
function field(page: Page, label: string) {
  return page.getByLabel(label, { exact: true }).filter({ visible: true });
}

function button(page: Page, name: string) {
  return page.getByRole("button", { name, exact: true }).filter({ visible: true });
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await field(page, "Email").fill(email);
  await field(page, "Password").fill(PASSWORD);
  await button(page, "Sign in").click();
  await expect(page).toHaveURL(/\/cases/);
}

async function signOut(page: Page) {
  await button(page, "Sign out").click();
  await expect(page).toHaveURL(/\/login/);
}

test("login → case → evidence → finding → independent review → PDF report", async ({ page }) => {
  const stamp = Date.now();
  const title = `E2E fake parcel fee SMS ${stamp}`;
  const claim = `The SMS in E1 links to parcel-fee-${stamp}.example and asks for a card payment.`;

  // ---- investigator opens a case and preserves evidence
  await signIn(page, LEAD);
  await page.getByRole("link", { name: "New case" }).click();
  await field(page, "Title").fill(title);
  await field(page, "Category").selectOption("phishing");
  await field(page, "Description").fill("Wave of SMS asking for a redelivery fee.");
  await button(page, "Create case").click();
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
  const caseUrl = page.url();

  await page.getByRole("link", { name: "Add evidence" }).click();
  await page.getByRole("tab", { name: "Written observation" }).click();
  await field(page, "Title").fill("SMS screenshot transcript");
  await field(page, "Observation").fill(`"Your parcel is held. Pay $2.99 at parcel-fee-${stamp}.example"`);
  await button(page, "Save evidence").click();
  await expect(page.getByText("SMS screenshot transcript")).toBeVisible();

  // Integrity check from the UI.
  await button(page, "Verify integrity").click();
  await expect(page.getByText(/Integrity verified/)).toBeVisible();

  // ---- finding: draft, then submit
  await page.getByRole("tab", { name: "Findings" }).click();
  await field(page, "Claim").fill(claim);
  await page.getByRole("checkbox").first().check();
  await button(page, "Save draft").click();
  await button(page, "Submit for review").click();
  await expect(page.getByText("in review").first()).toBeVisible();

  // The author cannot verify their own work: no Verify button is offered.
  await expect(button(page, "Verify")).toHaveCount(0);
  await signOut(page);

  // ---- a different person (reviewer) verifies it
  await signIn(page, REVIEWER);
  await page.getByRole("link", { name: "Review queue" }).click();
  const card = page.locator("section", { hasText: claim });
  await expect(card).toBeVisible();
  await card.getByLabel("Review note").fill("Checked against E1; hash verified.");
  await card.getByRole("button", { name: "Verify" }).click();
  await expect(card).toHaveCount(0);

  // ---- report: preview contains the verified finding; generate the PDF
  await page.goto(caseUrl);
  await page.getByRole("link", { name: "Report" }).click();
  await expect(page.getByText("1 verified findings")).toBeVisible();
  const preview = page.frameLocator('iframe[title="Report preview"]');
  await expect(preview.getByText(claim)).toBeVisible();
  await expect(preview.getByText("Prepared under the BLACK MAMBA Code").first()).toBeVisible();
  await button(page, "Generate PDF").click();
  const download = page.getByRole("link", { name: "Download PDF" });
  await expect(download).toBeVisible();

  const href = await download.getAttribute("href");
  const pdf = await page.request.get(href!);
  expect(pdf.ok()).toBeTruthy();
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");
});

test("a signed-out visitor is sent to the login page", async ({ page }) => {
  await page.goto("/cases");
  await expect(page).toHaveURL(/\/login\?next=%2Fcases/);
});
