import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import ApprovalCard, {
  type ApprovalCardProps,
} from "@/sections/approvals/ApprovalCard";
import messages from "@/i18n/messages/en.json";

const copy = messages.common.approvalCard;

function renderCard(props: Partial<ApprovalCardProps> = {}) {
  const onDecide = jest.fn(async () => {});
  const view = render(
    <ApprovalCard
      actions={[
        { id: "send", name: "Send message", description: "Posts a message" },
      ]}
      appName="Slack"
      payload={{ channel: "#general" }}
      expiresAt="2099-01-01T00:00:00Z"
      status="pending"
      onDecide={onDecide}
      {...props}
    />
  );
  return { ...view, onDecide };
}

afterEach(() => jest.restoreAllMocks());

const header = /^Approval requested: Send message in Slack/;

describe("pending", () => {
  it("shows the header with its deadline, the details, then the decisions", () => {
    renderCard();

    const trigger = screen.getByRole("button", { name: header });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    // The deadline sits in the header row, without seconds.
    expect(
      within(trigger).getByText(/^Approve by \d{1,2}:\d{2}\s?[AP]M$/)
    ).toBeVisible();
    // A single action is named only in the header.
    expect(screen.queryByText("Send message")).not.toBeInTheDocument();
    expect(screen.getAllByText("Posts a message")).toHaveLength(1);
    expect(screen.getAllByText("channel")).toHaveLength(1);
    expect(screen.getAllByText("#general")).toHaveLength(1);

    const value = screen.getByText("#general");
    const approve = screen.getByRole("button", {
      name: copy.approveOnce.ariaLabel,
    });
    expect(
      trigger.compareDocumentPosition(value) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    expect(
      value.compareDocumentPosition(approve) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("reports each decision", async () => {
    const user = setupUser();
    const { onDecide } = renderCard();

    await user.click(
      screen.getByRole("button", { name: copy.approveOnce.ariaLabel })
    );
    await user.click(
      screen.getByRole("button", { name: copy.approveSession.tooltip })
    );
    await user.click(
      screen.getByRole("button", { name: copy.reject.ariaLabel })
    );
    expect(onDecide.mock.calls).toEqual([
      ["approve_once"],
      ["approve_session"],
      ["reject"],
    ]);
  });

  it("names a single action alone when there is no app", () => {
    renderCard({ appName: undefined });
    expect(
      screen.getByRole("button", { name: /^Approval requested: Send message/ })
    ).toBeInTheDocument();
  });

  it("counts several actions and lists them in the details", () => {
    renderCard({
      actions: [
        { id: "send", name: "Send message", description: "Posts a message" },
        { id: "delete", name: "Delete message" },
      ],
    });
    expect(
      screen.getByRole("button", {
        name: /^Approval requested: 2 actions in Slack/,
      })
    ).toBeInTheDocument();
    expect(screen.getByText("Send message: Posts a message")).toBeVisible();
    expect(screen.getByText("Delete message")).toBeVisible();
  });

  it("labels the session approval for a chat and hides it when not allowed", () => {
    const { rerender, onDecide } = renderCard({ sessionScope: "chat" });
    expect(screen.getByText(copy.approveChat.button)).toBeInTheDocument();

    rerender(
      <ApprovalCard
        actions={[{ id: "send", name: "Send message" }]}
        payload={{}}
        status="pending"
        canApproveForSession={false}
        onDecide={onDecide}
      />
    );
    expect(screen.queryByText(copy.approveChat.button)).not.toBeInTheDocument();
    expect(
      screen.queryByText(copy.approveSession.button)
    ).not.toBeInTheDocument();
  });

  it("wraps long action text instead of cutting it", () => {
    const description = `Calls ${"/very/long/path".repeat(20)}`;
    const { unmount } = renderCard({
      actions: [{ id: "send", name: "Send message", description }],
    });
    expect(screen.getByText(description)).not.toHaveClass("truncate");
    const trigger = screen.getByRole("button", { name: header });
    const headline = within(trigger).getByText(
      "Approval requested: Send message in Slack"
    );
    expect(headline).not.toHaveClass("truncate");
    expect(headline.parentElement).not.toHaveClass("truncate");
    unmount();

    renderCard({
      actions: [
        { id: "send", name: "Send message", description },
        { id: "delete", name: "Delete message" },
      ],
    });
    expect(screen.getByText(`Send message: ${description}`)).not.toHaveClass(
      "truncate"
    );
  });

  it("disables the decisions while one is submitted", async () => {
    const user = setupUser();
    renderCard({ onDecide: () => new Promise<void>(() => {}) });
    await user.click(
      screen.getByRole("button", { name: copy.approveOnce.ariaLabel })
    );
    for (const name of [
      copy.approveOnce.ariaLabel,
      copy.approveSession.tooltip,
      copy.reject.ariaLabel,
    ]) {
      expect(screen.getByRole("button", { name })).toBeDisabled();
    }
  });

  it("collapses the details but keeps the decisions", async () => {
    const user = setupUser();
    renderCard();

    await user.click(screen.getByRole("button", { name: header }));

    expect(screen.getByRole("button", { name: header })).toHaveAttribute(
      "aria-expanded",
      "false"
    );
    expect(
      screen.getByRole("button", { name: copy.approveOnce.ariaLabel })
    ).toBeVisible();
  });

  it("reopens the details to show a failed decision", async () => {
    jest.spyOn(console, "error").mockImplementation(() => {});
    const user = setupUser();
    renderCard({ onDecide: () => Promise.reject(new Error("offline")) });
    await user.click(screen.getByRole("button", { name: header }));

    await user.click(
      screen.getByRole("button", { name: copy.reject.ariaLabel })
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      copy.submitError
    );
    expect(screen.getByRole("button", { name: header })).toHaveAttribute(
      "aria-expanded",
      "true"
    );
    expect(
      screen.getByRole("button", { name: copy.reject.ariaLabel })
    ).toBeEnabled();
  });

  it("announces the wait, then the decided record, in one live region", () => {
    const { rerender, onDecide } = renderCard();
    const region = screen.getByRole("status");
    expect(region).toHaveTextContent(
      "Approval requested: Send message in Slack"
    );

    rerender(
      <ApprovalCard
        actions={[{ id: "send", name: "Send message" }]}
        appName="Slack"
        payload={{}}
        status="approved"
        onDecide={onDecide}
      />
    );

    expect(screen.getByRole("status")).toBe(region);
    expect(region).toHaveTextContent("Approved: Send message in Slack");
  });
});

describe("decided", () => {
  it.each([
    ["chat", "Approved for this chat: Send message in Slack"],
    ["session", "Approved for this session: Send message in Slack"],
  ] as const)("records an approval for the %s", (sessionScope, text) => {
    renderCard({ status: "approvedForSession", sessionScope });
    expect(screen.getByRole("status")).toHaveTextContent(text);
  });

  it.each([
    ["approved", "Approved: Send message in Slack"],
    ["rejected", "Not approved: Send message in Slack"],
    ["expired", "Timed out: Send message in Slack"],
    ["closed", "No longer waiting: Send message in Slack"],
  ] as const)("leaves a one-line record of a %s request", (status, text) => {
    renderCard({ status });

    expect(screen.getByRole("status")).toHaveTextContent(text);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("#general")).not.toBeInTheDocument();
  });
});
