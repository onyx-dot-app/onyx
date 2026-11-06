import { expect, test } from "@playwright/test";
import { CraftChatOutputsPage } from "@tests/e2e/pages/CraftChatOutputsPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type { Settings } from "@/lib/settings/types";
import type {
  ApiDetailedSessionResponse,
  ApiInteractiveTurnResponse,
  ApiMessageResponse,
  OutputCard,
} from "@/app/craft/types/streamingTypes";

test.beforeEach(async ({ page }, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const settingsResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBe(true);
  const settings: Settings = await settingsResponse.json();
  test.skip(
    settings.onyx_craft_enabled !== true,
    "Onyx Craft is disabled in this environment"
  );
});

test("restores output cards, moves updated files, and scopes overflow to their turn", async ({
  page,
}) => {
  const api = new OnyxApiClient(page.request);
  const sessionId = await api.createCraftSession("E2E chat output cards");
  const chat = new CraftChatOutputsPage(page);
  const names = ["apple.md", "banana.md", "cherry.md", "delta.md", "zulu.md"];
  let cards: OutputCard[] = names.map((name, index) => ({
    id: `00000000-0000-4000-8000-00000000000${index + 1}`,
    kind: "file",
    path: `outputs/${name}`,
    name,
    turn_index: index < 4 ? 0 : 1,
    revision: 1,
    size_bytes: 30,
    deleted: false,
    viewed_revision: null,
  }));
  const firstId = "00000000-0000-4000-8000-000000000001";
  const appId = "00000000-0000-4000-8000-000000000006";
  cards.push({
    id: appId,
    kind: "app",
    path: "outputs/web",
    name: "Local App",
    turn_index: 1,
    revision: 1,
    size_bytes: null,
    deleted: false,
    viewed_revision: null,
  });
  const messages: ApiMessageResponse[] = [0, 1].flatMap((turn) =>
    (["user", "assistant"] as const).map((type, offset) => {
      const content =
        type === "user"
          ? `Make outputs ${turn + 1}`
          : `Finished outputs ${turn + 1}`;
      return {
        id: `00000000-0000-4000-8000-00000000001${turn * 2 + offset}`,
        session_id: sessionId,
        turn_index: turn,
        type,
        content,
        created_at: new Date(
          Date.UTC(2026, 0, 1, 0, turn, offset)
        ).toISOString(),
        message_metadata: {
          type: type === "user" ? "user_message" : "agent_message",
          content: { type: "text", text: content },
        },
      };
    })
  );
  const viewedRequests: Array<{ id: string; revision: number }> = [];
  // The API fixture survives browser reload. Backend integration tests verify database persistence separately.
  await page.route(`**/api/build/sessions/${sessionId}/messages`, (route) =>
    route.fulfill({ json: { messages } })
  );
  await page.route(`**/api/build/sessions/${sessionId}/output-cards`, (route) =>
    route.fulfill({ json: { cards } })
  );
  await page.route(
    `**/api/build/sessions/${sessionId}/output-cards/*/viewed`,
    async (route) => {
      expect(route.request().method()).toBe("PATCH");
      const id = new URL(route.request().url()).pathname.split("/").at(-2);
      const body: { revision: number } = route.request().postDataJSON();
      const card = cards.find((candidate) => candidate.id === id);
      if (!card || body.revision > card.revision) {
        await route.fulfill({ status: 409 });
        return;
      }
      card.viewed_revision = Math.max(card.viewed_revision ?? 0, body.revision);
      viewedRequests.push({ id: card.id, revision: body.revision });
      await route.fulfill({ json: card });
    }
  );
  await page.route(`**/api/build/sessions/${sessionId}/outputs`, (route) =>
    route.fulfill({
      json: {
        files: cards
          .filter((card) => card.kind === "file")
          .map((card) => ({
            path: card.path,
            revision: String(card.revision),
            size: card.size_bytes,
          })),
        complete: true,
      },
    })
  );
  await page.route(
    `**/api/build/sessions/${sessionId}/artifacts/outputs/*.md*`,
    (route) =>
      route.fulfill({
        contentType: "text/markdown",
        body: "# Completed output\n",
      })
  );
  try {
    await chat.outputs.goto(sessionId);
    await chat.expectCards(0, ["apple.md", "banana.md", "cherry.md"]);
    await chat.viewAll(0, 4);
    await chat.expectUnread("outputs/apple.md", true);
    await chat.expectOutput("outputs/delta.md", true);
    await chat.expectOutput("outputs/zulu.md", false);
    await chat.showAllTurns();
    await chat.expectOutput("outputs/zulu.md", true);
    expect(viewedRequests).toEqual([]);
    await chat.outputs.close();
    await chat.openCard(firstId, "apple.md");
    await chat.expectActiveTab("apple.md");
    await chat.selectTab("Outputs");
    await chat.expectUnread("outputs/apple.md", false);
    await expect
      .poll(() => viewedRequests)
      .toContainEqual({ id: firstId, revision: 1 });
    await chat.outputs.reload();
    await chat.expectCardAtTurn(firstId, 0);
    await chat.expectUnread("outputs/apple.md", false);

    cards = cards.map((card) =>
      card.id === firstId ? { ...card, turn_index: 1, revision: 2 } : card
    );
    await chat.outputs.reload();
    await chat.expectCards(0, ["banana.md", "cherry.md", "delta.md"]);
    await chat.expectCardAtTurn(firstId, 1);
    await chat.expectUnread("outputs/apple.md", true);
    await chat.openCard(appId, "Preview your app");
    await chat.expectActiveTab("Apps");
  } finally {
    await api.deleteCraftSession(sessionId);
  }
});

for (const completionTransport of ["stream", "recovery"] as const) {
  test(`keeps the response active until ${completionTransport} completion and shows cards before slow inventory finishes`, async ({
    page,
  }) => {
    const api = new OnyxApiClient(page.request);
    const sessionId = await api.createCraftSession("E2E output finalization");
    const chat = new CraftChatOutputsPage(page);
    const prompt = "Create the final report";
    const answer = "The report is ready.";
    const turnId = "00000000-0000-4000-8000-000000000021";
    const output: OutputCard = {
      id: "00000000-0000-4000-8000-000000000022",
      kind: "file",
      path: "outputs/report.md",
      name: "report.md",
      turn_index: 0,
      revision: 1,
      size_bytes: 30,
      deleted: false,
      viewed_revision: null,
    };
    const session: ApiDetailedSessionResponse = {
      id: sessionId,
      user_id: null,
      name: "E2E output finalization",
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
      last_activity_at: "2026-01-01T00:00:00Z",
      nextjs_port: null,
      sandbox: {
        id: "00000000-0000-4000-8000-000000000023",
        status: "running",
        container_id: null,
        created_at: "2026-01-01T00:00:00Z",
        last_heartbeat: null,
      },
      artifacts: [],
      sharing_scope: "private",
      origin: "INTERACTIVE",
      agent_provider: null,
      agent_model: null,
      skills_stale: false,
      session_loaded_in_sandbox: true,
    };
    const messages: ApiMessageResponse[] = (["user", "assistant"] as const).map(
      (type, index) => ({
        id: `00000000-0000-4000-8000-00000000003${index}`,
        session_id: sessionId,
        turn_index: 0,
        type,
        content: type === "user" ? prompt : answer,
        created_at: "2026-01-01T00:00:00Z",
        message_metadata: {
          type: type === "user" ? "user_message" : "agent_message",
          content: { type: "text", text: type === "user" ? prompt : answer },
        },
      })
    );
    let sent = false;
    let committed = false;
    let completionPolls = 0;
    let successorChecks = 0;
    let knownTurnReads = 0;
    let cardReads = 0;
    let initialInventoryReads = 0;
    let finalInventoryReads = 0;
    let releaseInventory = () => {};
    const inventoryGate = new Promise<void>((resolve) => {
      releaseInventory = resolve;
    });
    const errors: string[] = [];
    const turn = (): ApiInteractiveTurnResponse => ({
      session_id: sessionId,
      turn_id: turnId,
      turn_index: 0,
      status: committed ? "SUCCEEDED" : "RUNNING",
    });
    const sessionUrl = `**/api/build/sessions/${sessionId}`;
    await page.route(sessionUrl, (route) => route.fulfill({ json: session }));
    await page.route(`${sessionUrl}/sandbox-status`, (route) =>
      route.fulfill({ json: { status: "running" } })
    );
    await page.route(`${sessionUrl}/artifacts`, (route) =>
      route.fulfill({ json: [] })
    );
    await page.route(`${sessionUrl}/files*`, (route) =>
      route.fulfill({ json: { path: "", entries: [] } })
    );
    await page.route(`${sessionUrl}/messages`, (route) =>
      route.fulfill({ json: { messages: committed ? messages : [] } })
    );
    await page.route(`${sessionUrl}/send-message`, async (route) => {
      expect(route.request().method()).toBe("POST");
      expect(route.request().postDataJSON()).toMatchObject({ content: prompt });
      sent = true;
      await route.fulfill({ json: turn() });
    });
    await page.route(`${sessionUrl}/turns/active`, (route) => {
      if (sent && !committed) completionPolls += 1;
      if (sent && committed) successorChecks += 1;
      return route.fulfill({ json: sent && !committed ? turn() : null });
    });
    await page.route(`${sessionUrl}/turns/${turnId}`, (route) => {
      knownTurnReads += 1;
      return route.fulfill({ json: turn() });
    });
    const packets = [
      {
        type: "tool_call_start",
        tool_call_id: "write-report",
        kind: "execute",
        status: "in_progress",
        title: "Create report",
        _meta: { toolName: "bash" },
      },
      {
        type: "tool_call_progress",
        tool_call_id: "write-report",
        kind: "execute",
        status: "completed",
        _meta: { toolName: "bash" },
      },
      {
        type: "agent_message_chunk",
        content: { type: "text", text: answer },
      },
    ];
    const completionEvent = "craft-test-completion";
    if (completionTransport === "stream") {
      // Playwright route.fulfill buffers bodies; this fixture keeps the SSE reader open.
      await page.addInitScript(
        ({ eventsPath, packets, completionEvent, completion }) => {
          const fetch = window.fetch.bind(window);
          window.fetch = (input, init) => {
            const url = input instanceof Request ? input.url : String(input);
            if (
              new URL(url, window.location.href).href !==
              new URL(eventsPath, window.location.origin).href
            )
              return fetch(input, init);
            const encoder = new TextEncoder();
            const encode = (packet: object) =>
              encoder.encode(
                `event: message\ndata: ${JSON.stringify(packet)}\n\n`
              );
            let complete: () => void;
            const body = new ReadableStream<Uint8Array>({
              start(controller) {
                packets.forEach((packet) => controller.enqueue(encode(packet)));
                complete = () => {
                  controller.enqueue(encode(completion));
                  controller.close();
                };
                window.addEventListener(completionEvent, complete, {
                  once: true,
                });
              },
              cancel() {
                window.removeEventListener(completionEvent, complete);
              },
            });
            return Promise.resolve(
              new Response(body, {
                headers: { "Content-Type": "text/event-stream" },
              })
            );
          };
        },
        {
          eventsPath: `/api/build/sessions/${sessionId}/turns/${turnId}/events`,
          packets,
          completionEvent,
          completion: {
            ...turn(),
            type: "turn_completed",
            status: "SUCCEEDED",
          },
        }
      );
    } else {
      await page.route(`${sessionUrl}/turns/${turnId}/events`, (route) =>
        route.fulfill({
          contentType: "text/event-stream",
          body: [...packets, { type: "prompt_response" }]
            .map(
              (packet) => `event: message\ndata: ${JSON.stringify(packet)}\n\n`
            )
            .join(""),
        })
      );
    }
    await page.route(`${sessionUrl}/output-cards`, (route) => {
      cardReads += 1;
      return route.fulfill({ json: { cards: committed ? [output] : [] } });
    });
    await page.route(`${sessionUrl}/outputs`, async (route) => {
      if (sent) {
        finalInventoryReads += 1;
        await inventoryGate;
      } else initialInventoryReads += 1;
      await route.fulfill({ json: { files: [], complete: true } });
    });
    try {
      await chat.outputs.goto(sessionId);
      await expect.poll(() => initialInventoryReads).toBe(1);
      await expect.poll(() => cardReads).toBe(1);
      page.on("pageerror", (error) => errors.push(error.message));
      await chat.send(prompt);
      if (completionTransport === "recovery")
        await expect.poll(() => completionPolls).toBeGreaterThanOrEqual(3);
      await chat.expectFinalizing(answer, true);
      await chat.expectCards(0, []);
      expect(cardReads).toBe(1);
      expect(finalInventoryReads).toBe(0);
      if (completionTransport === "stream") expect(completionPolls).toBe(0);

      committed = true;
      if (completionTransport === "stream")
        await page.evaluate(
          (eventName) => window.dispatchEvent(new Event(eventName)),
          completionEvent
        );
      await chat.expectCards(0, [output.name]);
      await chat.expectFinalizing(answer, false);
      await expect.poll(() => finalInventoryReads).toBe(1);
      expect(cardReads).toBe(2);
      const inventoryResponse = page.waitForResponse((response) =>
        response.url().endsWith(`/build/sessions/${sessionId}/outputs`)
      );
      releaseInventory();
      await (await inventoryResponse).finished();
      await chat.expectCards(0, [output.name]);
      expect(finalInventoryReads).toBe(1);
      if (completionTransport === "stream") {
        expect(knownTurnReads).toBe(0);
        expect(successorChecks).toBe(1);
      }
      expect(errors).toEqual([]);
    } finally {
      releaseInventory();
      await api.deleteCraftSession(sessionId);
    }
  });
}
