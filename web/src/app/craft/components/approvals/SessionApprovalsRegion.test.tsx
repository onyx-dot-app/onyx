import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import SessionApprovalsRegion from "@/app/craft/components/approvals/SessionApprovalsRegion";
import type { ApprovalView } from "@/app/craft/types/approvals";

// Stored outcomes
describe("Approval history", () => {
  it.each(["APPROVED", "REJECTED"] as const)(
    "retains the %s outcome after refreshing the session query",
    async (decision) => {
      const user = setupUser();
      let approval: ApprovalView = {
        approval_id: "request",
        session_id: "session",
        actions: [
          {
            action_type: "send",
            display_name: "Send message",
            description: "",
            policy: "ASK",
          },
        ],
        app_name: "Slack",
        payload: {},
        display_payload: {},
        created_at: "2026-10-01T00:00:00Z",
        expires_at: null,
        decision: null,
        decided_at: null,
        is_live: true,
      };
      const fetchMock = jest
        .spyOn(global, "fetch")
        .mockImplementation(async (url, options) => {
          if (options?.method === "POST") {
            approval = { ...approval, decision, is_live: false };
            return new Response(JSON.stringify(approval), { status: 200 });
          }
          if (String(url).endsWith("/status")) {
            return new Response(
              JSON.stringify([
                {
                  approval_id: approval.approval_id,
                  decision: approval.decision,
                  is_live: approval.is_live,
                },
              ]),
              { status: 200 }
            );
          }
          return new Response(JSON.stringify({ items: [approval] }), {
            status: 200,
          });
        });
      render(<SessionApprovalsRegion sessionId="session" />);
      await user.click(
        await screen.findByRole("button", {
          name:
            decision === "APPROVED" ? /approve.*once/i : "Reject this action",
        })
      );
      await waitFor(
        () =>
          expect(
            fetchMock.mock.calls.filter(
              ([url, options]) =>
                !options?.method && !String(url).endsWith("/status")
            )
          ).toHaveLength(2),
        { timeout: 2000 }
      );
      expect(
        screen.getByText(
          decision === "APPROVED"
            ? "Approved"
            : "Request rejected. This request did not run."
        )
      ).toBeInTheDocument();
      fetchMock.mockRestore();
    }
  );
});

// Metadata polling
describe("Approval status polling", () => {
  it("polls metadata and reloads full history only when request status changes", async () => {
    jest.useFakeTimers();
    let status: {
      approval_id: string;
      decision: string | null;
      is_live: boolean;
    }[] = [];
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockImplementation(
        async (url) =>
          new Response(
            JSON.stringify(
              String(url).endsWith("/status") ? status : { items: [] }
            ),
            { status: 200 }
          )
      );
    try {
      render(<SessionApprovalsRegion sessionId="poll-session" />);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(1);
      });
      const historyCalls = () =>
        fetchMock.mock.calls.filter(([url]) =>
          String(url).endsWith("/poll-session")
        );
      expect(historyCalls()).toHaveLength(1);
      await act(async () => {
        await jest.advanceTimersByTimeAsync(10_000);
      });
      expect(historyCalls()).toHaveLength(1);
      for (const change of [
        [{ approval_id: "first", decision: null, is_live: false }],
        [{ approval_id: "first", decision: "APPROVED", is_live: false }],
        [{ approval_id: "new", decision: null, is_live: true }],
      ]) {
        status = change;
        const before = historyCalls().length;
        await act(async () => {
          await jest.advanceTimersByTimeAsync(10_000);
        });
        expect(historyCalls()).toHaveLength(before + 1);
      }
    } finally {
      fetchMock.mockRestore();
      jest.useRealTimers();
    }
  });

  it("refreshes history when the first status poll finds a newer request", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockImplementation(
        async (url) =>
          new Response(
            JSON.stringify(
              String(url).endsWith("/status")
                ? [{ approval_id: "new", decision: null, is_live: true }]
                : { items: [] }
            ),
            { status: 200 }
          )
      );
    try {
      render(<SessionApprovalsRegion sessionId="initial-race" />);
      await waitFor(() =>
        expect(
          fetchMock.mock.calls.filter(([url]) =>
            String(url).endsWith("/initial-race")
          )
        ).toHaveLength(2)
      );
    } finally {
      fetchMock.mockRestore();
    }
  });
});
