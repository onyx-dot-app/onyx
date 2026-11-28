import { test } from "@playwright/test";
import { AdminDecisionModelsPage } from "@tests/e2e/pages/AdminDecisionModelsPage";

test("Decision models are on AI Models and keep selection opt-in", async ({
  page,
}) => {
  const decisionModels = new AdminDecisionModelsPage(page);
  await decisionModels.open();
  await decisionModels.expectUnsetModel();
});

test("Zoom setup provides shared credentials directly on AI Models", async ({
  page,
}) => {
  const decisionModels = new AdminDecisionModelsPage(page);
  await decisionModels.open();
  await decisionModels.openZoomSetup();
});
