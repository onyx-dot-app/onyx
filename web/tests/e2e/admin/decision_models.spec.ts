import { test } from "@playwright/test";
import { AdminDecisionModelsPage } from "@tests/e2e/pages/AdminDecisionModelsPage";

test("Decision Models has its own admin page and keeps selection opt-in", async ({
  page,
}) => {
  const decisionModels = new AdminDecisionModelsPage(page);
  await decisionModels.openFromChatPreferences();
  await decisionModels.expectUnsetModel();
});

test("Zoom Decisions setup loads saved Scribe connection sources", async ({
  page,
}) => {
  const decisionModels = new AdminDecisionModelsPage(page);
  await decisionModels.openFromChatPreferences();
  await decisionModels.openZoomSetup();
});
