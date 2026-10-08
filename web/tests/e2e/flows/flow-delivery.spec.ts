import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { FlowsPage } from "@tests/e2e/pages/FlowsPage";

/**
 * Waiting on somebody else's system, and telling somebody else's system.
 *
 * Both of these steps only do anything interesting against a real endpoint,
 * and the deployment's SSRF policy quite rightly will not let a flow reach one
 * on this machine. So what is covered here is the half that lives in the
 * browser: the fields, the numbers the editor works out for you, and the
 * signing key a webhook step has to hand you. How the steps behave once the
 * request goes out is covered by the node tests.
 */
test.describe("Flows retry and webhook steps", () => {
  test("a retry step says how long it will wait", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    await flows.selectNode("http");
    await flows.addStep("Retry");
    await flows.selectNode("retry");

    // Ten checks five seconds apart, worked out and shown rather than left
    // for the author to multiply in their head.
    await flows.expectInspectorContains("50 seconds");

    await flows.fillField("Seconds between checks", "30");
    await flows.expectInspectorContains("300 seconds");

    // The server caps one step at 600s, so the editor must not let an author
    // build a spec it will refuse.
    await flows.fillField("How many checks", "99");
    await flows.expectFieldValue("How many checks", "60");
  });

  test("a retry step only asks for a value when the operator needs one", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Retry");
    await flows.selectNode("retry");

    await flows.expectField("Expected value");
    await flows.selectOperator("is not empty");
    await flows.expectNoField("Expected value");
  });

  test("a webhook step hands over the key its receiver needs", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();
    await flows.selectNode("http");
    await flows.addStep("Webhook");
    await flows.selectNode("webhook");

    const shown = await flows.readSigningSecret();
    expect(shown.length).toBeGreaterThan(20);

    // The same key the API serves, not a placeholder: a receiver configured
    // from this screen has to verify what the worker actually signs with.
    const res = await page.request.get(`/api/flows/${flows.flowIdFromUrl()}`);
    const flow: { webhook_signing_secret: string | null } = await res.json();
    expect(shown).toBe(flow.webhook_signing_secret);
  });

  test("both kinds round-trip through the server's validation", async ({
    page,
  }, testInfo) => {
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const flows = new FlowsPage(page);
    await flows.gotoList();
    await flows.createFlow();

    await flows.selectNode("http");
    await flows.addStep("Retry");
    await flows.selectNode("retry");
    await flows.fillField("URL", "https://api.example.com/exports/1");
    await flows.fillField("Wait until this part of the response", "state");
    await flows.fillField("Expected value", "complete");

    await flows.addStep("Webhook");
    await flows.selectNode("webhook");
    await flows.fillField("URL", "https://hooks.example.com/incoming");

    // Saving is the real check: the server parses the spec and rejects
    // anything it cannot execute.
    await flows.save();
    await flows.reload();
    await flows.expectStepCount(3);

    await flows.selectNode("retry");
    await flows.expectFieldValue("Expected value", "complete");
  });
});
