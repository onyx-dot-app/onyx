import { readFile } from "node:fs/promises";
import { expect, test } from "@playwright/test";
import { boolean, object, type ObjectSchema } from "yup";
import type { Settings } from "@/lib/settings/types";
import { CraftSessionPage } from "@tests/e2e/pages/CraftSessionPage";
import { CraftWelcomePage } from "@tests/e2e/pages/CraftWelcomePage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import {
  addMockLlmConversation,
  mockLlmNonce,
  releaseMockLlmStream,
} from "@tests/e2e/utils/mockLlm";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

const craftSettingsSchema: ObjectSchema<Pick<Settings, "onyx_craft_enabled">> =
  object({ onyx_craft_enabled: boolean().optional() }).required();

test.beforeEach(async ({ page }, testInfo) => {
  test.setTimeout(300_000);
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const settingsResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBe(true);
  const body: unknown = await settingsResponse.json();
  const settings = await craftSettingsSchema.validate(body, { strict: true });
  const craftEnabled = settings.onyx_craft_enabled === true;
  if (process.env.ENABLE_CRAFT === "true") {
    expect(craftEnabled, "The test deployment must enable Craft").toBe(true);
  }
  test.skip(!craftEnabled, "Onyx Craft is disabled in this environment");
});

test("Craft creates a session from welcome and serves generated Next preview", async ({
  page,
}, testInfo) => {
  const nonce = mockLlmNonce();
  const bootstrapCallId = `bootstrap-${nonce}`;
  const writeCallId = `write-${nonce}`;
  const fileName = "preview-proof.txt";
  const content = `Craft preview output ${nonce}\n`;
  const heading = `Craft generated preview ${nonce}`;
  const streamingText = "Starting the generated web app. ";
  const completedText = "The generated preview is ready.";
  const writeCommand = [
    "set -eu",
    "cat > outputs/web/app/layout.tsx <<'CRAFT_LAYOUT'",
    'import type { ReactNode } from "react";',
    "export default function Layout({ children }: { children: ReactNode }) {",
    "  return <html><body>{children}</body></html>;",
    "}",
    "CRAFT_LAYOUT",
    "cat > outputs/web/app/page.tsx <<'CRAFT_PAGE'",
    '"use client";',
    'import { useState } from "react";',
    "export default function Page() {",
    "  const [count, setCount] = useState(0);",
    "  return <main>",
    `    <h1>Craft generated preview ${nonce}</h1>`,
    "    <button onClick={() => setCount((value) => value + 1)}>Count {count}</button>",
    "  </main>;",
    "}",
    "CRAFT_PAGE",
    `printf 'Craft preview output ${nonce}\\n' > outputs/${fileName}`,
    "printf 'generated preview written\\n'",
  ].join("\n");
  await addMockLlmConversation({
    name: nonce,
    conditions: { prompt_contains: [nonce], offers: ["bash"] },
    replies: [
      {
        text: streamingText.repeat(3),
        pause_after_first_chunk: nonce,
        tool_calls: [
          {
            id: bootstrapCallId,
            name: "bash",
            arguments: {
              command: "bash start-webapp.sh",
              description: "Start the managed Next web app",
            },
          },
        ],
      },
      {
        conditions: { has_results_for: [bootstrapCallId] },
        tool_calls: [
          {
            id: writeCallId,
            name: "bash",
            arguments: {
              command: writeCommand,
              description: "Write the generated preview and downloadable proof",
            },
          },
        ],
      },
      {
        text: `${completedText} [${fileName}](outputs/${fileName})`,
        conditions: { has_results_for: [writeCallId] },
      },
    ],
  });
  const api = new OnyxApiClient(page.request);
  const craft = new CraftSessionPage(page);
  const welcome = new CraftWelcomePage(page);
  let ownedSessionId: string | undefined;
  const created = craft
    .observeSessionCreation()
    .then(async (response) => {
      const sessionId = await craft.createdSessionId(response);
      ownedSessionId = sessionId;
      return { response, sessionId };
    })
    .then(
      (creation) => ({ kind: "created" as const, ...creation }),
      (error: unknown) => ({ kind: "failed" as const, error })
    );
  try {
    await welcome.goto();
    const creation = await created;
    if (creation.kind === "failed") throw creation.error;
    const { response, sessionId } = creation;
    const sandboxId = await craft.expectCreatedSessionReady(response);
    await testInfo.attach("craft-welcome-session", {
      body: JSON.stringify({ sessionId, sandboxId }),
      contentType: "application/json",
    });
    await welcome.dismissIntroIfPresentAndExpectReady();
    await craft.selectMockModel();
    await craft.send(`Generate the interactive Next preview. ${nonce}`, {
      sessionId,
    });
    await craft.expectPartialReply(streamingText.trim());
    await releaseMockLlmStream(nonce);
    await craft.expectCompletedReply(completedText, 120_000);
    await craft.openOutput(fileName, content);
    await craft.expectGeneratedPreview({ sessionId, heading });
    const download = await craft.downloadOutput(fileName);
    expect(download.suggestedFilename()).toBe(fileName);
    const downloadedPath = await download.path();
    if (!downloadedPath)
      throw new Error("The browser did not save the generated preview output");
    expect(await readFile(downloadedPath)).toEqual(
      Buffer.from(content, "utf8")
    );
    await craft.reload();
    await craft.expectCompletedReply(completedText);
    await craft.openOutput(fileName, content);
    await craft.expectGeneratedPreview({ sessionId, heading });
  } finally {
    await created;
    try {
      await releaseMockLlmStream(nonce);
    } finally {
      if (ownedSessionId) await api.deleteCraftSession(ownedSessionId);
    }
  }
});

test("Craft streams a real tool turn and keeps its downloadable output after reload", async ({
  page,
}) => {
  const nonce = mockLlmNonce();
  const callId = `call-${nonce}`;
  const fileName = "runtime-proof.txt";
  const content = `Craft sandbox output ${nonce}\n`;
  const streamingText = "Creating the proof file. ";
  const completedText = "The sandbox file is ready.";
  await addMockLlmConversation({
    name: nonce,
    conditions: { prompt_contains: [nonce], offers: ["bash"] },
    replies: [
      {
        text: streamingText.repeat(3),
        pause_after_first_chunk: nonce,
        tool_calls: [
          {
            id: callId,
            name: "bash",
            arguments: {
              command: `mkdir -p outputs && printf 'Craft sandbox output ${nonce}\\n' > outputs/${fileName} && printf 'proof file created\\n'`,
              description: "Create the downloadable sandbox proof file",
            },
          },
        ],
      },
      {
        text: `${completedText} [${fileName}](outputs/${fileName})`,
        conditions: { has_results_for: [callId] },
      },
    ],
  });
  const api = new OnyxApiClient(page.request);
  const sessionId = await api.createCraftSession("Craft runtime proof");
  const craft = new CraftSessionPage(page);
  try {
    await craft.goto(sessionId);
    await craft.selectMockModel();
    await craft.send(`Create the sandbox proof file. ${nonce}`);
    await craft.expectPartialReply(streamingText.trim());
    await releaseMockLlmStream(nonce);
    await craft.expectCompletedReply(completedText);
    await craft.openOutput(fileName, content);
    const download = await craft.downloadOutput(fileName);
    expect(download.suggestedFilename()).toBe(fileName);
    const downloadedPath = await download.path();
    if (!downloadedPath)
      throw new Error("The browser did not save the sandbox output");
    expect(await readFile(downloadedPath, "utf8")).toBe(content);
    await craft.reload();
    await craft.expectCompletedReply(completedText);
    await craft.openOutput(fileName, content);
  } finally {
    try {
      await releaseMockLlmStream(nonce);
    } finally {
      await api.deleteCraftSession(sessionId);
    }
  }
});

test("Craft stops a streaming turn and accepts the next message", async ({
  page,
}) => {
  const nonce = mockLlmNonce();
  const streamingText = "This reply will be stopped. ";
  const completedText = "The next turn completed.";
  const nextNonce = mockLlmNonce();
  await addMockLlmConversation({
    name: nonce,
    conditions: { prompt_contains: [nonce], offers: ["bash"] },
    replies: [
      { text: streamingText.repeat(3), pause_after_first_chunk: nonce },
    ],
  });
  await addMockLlmConversation({
    name: nextNonce,
    conditions: { prompt_contains: [nextNonce], offers: ["bash"] },
    replies: [{ text: completedText }],
  });
  const api = new OnyxApiClient(page.request);
  const sessionId = await api.createCraftSession("Craft cancellation proof");
  const craft = new CraftSessionPage(page);
  try {
    await craft.goto(sessionId);
    await craft.selectMockModel();
    const turnId = await craft.send(`Start a reply so I can stop it. ${nonce}`);
    await craft.expectPartialReply(streamingText.trim());
    await craft.stop();
    await releaseMockLlmStream(nonce);
    await expect
      .poll(
        async () => {
          const response = await page.request.get(
            `/api/build/sessions/${sessionId}/turns/${turnId}`
          );
          expect(response.ok()).toBe(true);
          const turn: { status: string } | null = await response.json();
          return turn?.status;
        },
        { timeout: 30_000 }
      )
      .toBe("CANCELLED");
    await craft.send(`Finish a new reply. ${nextNonce}`);
    await craft.expectCompletedReply(completedText);
    await craft.reload();
    await craft.expectCompletedReply(completedText);
  } finally {
    try {
      await releaseMockLlmStream(nonce);
    } finally {
      await api.deleteCraftSession(sessionId);
    }
  }
});
