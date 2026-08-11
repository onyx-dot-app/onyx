import { test } from "@playwright/test";
import { AdminChromePage } from "@tests/e2e/pages/AdminChromePage";

test.use({
  storageState: "admin_auth.json",
  viewport: { width: 390, height: 800 },
});
test.describe.configure({ mode: "parallel" });

// The create-connector page renders its own sidebar instead of the default one.
// It must still offer the same way back to it as every other admin page.
const ADMIN_PAGES = [
  { name: "an admin page", path: "/admin/indexing/status" },
  { name: "the create-connector page", path: "/admin/connectors/web" },
];

for (const { name, path } of ADMIN_PAGES) {
  test(`Folded sidebar can be re-opened on ${name} – mobile`, async ({
    page,
  }) => {
    const adminChrome = new AdminChromePage(page);

    await adminChrome.goto(path);
    await adminChrome.closeSidebar();
    await adminChrome.expectSidebarFolded();

    await adminChrome.expectOpenSidebarButtonVisible();
    await adminChrome.openSidebar();
    await adminChrome.expectSidebarUnfolded();
  });
}
