import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { SlackTokensForm } from "@/app/admin/bots/SlackTokensForm";

const mockToastError = jest.fn();
const mockToastSuccess = jest.fn();

jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

const emptyBot = {
  name: "",
  enabled: true,
  bot_token: "",
  app_token: "",
  user_token: "",
};

let fetchSpy: jest.SpyInstance;

beforeEach(() => {
  fetchSpy = jest.spyOn(global, "fetch");
});

afterEach(() => {
  fetchSpy.mockRestore();
  jest.clearAllMocks();
});

async function fillAndSubmitNewBot() {
  const user = setupUser();
  render(
    <SlackTokensForm
      isUpdate={false}
      initialValues={emptyBot}
      router={{ push: jest.fn() }}
    />
  );

  await user.type(screen.getByLabelText(/name this slack bot/i), "Support");
  await user.type(screen.getByLabelText(/slack bot token/i), "xoxb-1");
  await user.type(screen.getByLabelText(/slack app token/i), "xapp-1");
  await user.click(screen.getByRole("button", { name: /create/i }));
}

test("shows an error toast when the error response is not JSON", async () => {
  // Mock POST /api/manage/admin/slack-app/bots (proxy error page)
  fetchSpy.mockResolvedValueOnce({
    ok: false,
    status: 502,
    json: async () => {
      throw new SyntaxError("Unexpected token '<'");
    },
  } as unknown as Response);

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - Unexpected server response (HTTP 502)"
    );
  });
  expect(mockToastSuccess).not.toHaveBeenCalled();
});

test("shows an error toast when the JSON body has no detail or message", async () => {
  // Mock POST /api/manage/admin/slack-app/bots (JSON without detail/message)
  fetchSpy.mockResolvedValueOnce({
    ok: false,
    status: 500,
    json: async () => ({}),
  } as unknown as Response);

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - Unexpected server response (HTTP 500)"
    );
  });
});

test("maps an invalid bot token detail to the translated message", async () => {
  // Mock POST /api/manage/admin/slack-app/bots (backend token validation)
  fetchSpy.mockResolvedValueOnce({
    ok: false,
    status: 400,
    json: async () => ({ detail: "Invalid bot token: invalid_auth" }),
  } as unknown as Response);

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - Slack Bot Token is invalid"
    );
  });
});

test("shows the backend detail for other errors", async () => {
  // Mock POST /api/manage/admin/slack-app/bots (generic backend error)
  fetchSpy.mockResolvedValueOnce({
    ok: false,
    status: 400,
    json: async () => ({ detail: "A bot with this name already exists" }),
  } as unknown as Response);

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - A bot with this name already exists"
    );
  });
});
