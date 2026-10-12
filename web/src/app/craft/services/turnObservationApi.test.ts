/** @jest-environment jsdom */
import {
  fetchActiveTurn,
  fetchKnownTurn,
  fetchTurnEventStream,
  fetchScheduledRunContext,
  fetchScheduledRunEventStream,
  interruptMessageStream,
} from "@/app/craft/services/apiServices";

const originalFetch = global.fetch;
beforeEach(() => {
  global.fetch = jest.fn();
});
afterEach(() => {
  global.fetch = originalFetch;
});

it.each([
  ["active turn", () => fetchActiveTurn("session")],
  ["known turn", () => fetchKnownTurn("session", "turn")],
  ["turn events", () => fetchTurnEventStream("session", "turn")],
  ["scheduled context", () => fetchScheduledRunContext("session")],
  ["scheduled events", () => fetchScheduledRunEventStream("session")],
] as const)("preserves permission status for %s", async (_name, read) => {
  jest
    .mocked(fetch)
    .mockResolvedValue(
      new Response(JSON.stringify({ detail: "Access denied" }), { status: 403 })
    );
  await expect(read()).rejects.toMatchObject({ status: 403 });
});

it("targets Stop at the accepted turn", async () => {
  jest
    .mocked(fetch)
    .mockResolvedValue(new Response(JSON.stringify({ interrupted: true })));
  await interruptMessageStream("session", "turn");
  expect(fetch).toHaveBeenCalledWith(
    "/api/build/sessions/session/interrupt?turn_id=turn",
    { method: "POST" }
  );
});
