import { expect, test } from "@playwright/test";
import { CraftChatOutputsPage } from "@tests/e2e/pages/CraftChatOutputsPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type {
  ApiMessageResponse,
  OutputCard,
} from "@/app/craft/types/streamingTypes";

test("restores output cards, moves updated files, and scopes overflow to their turn", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
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
