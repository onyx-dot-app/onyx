import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { SlackTokensForm } from "@/app/admin/bots/SlackTokensForm";

const mockToastError = jest.fn();
const mockToastSuccess = jest.fn();
const mockGo = jest.fn();

jest.mock("@opal/layouts", () => ({
  ...jest.requireActual<typeof import("@opal/layouts")>("@opal/layouts"),
  toast: {
    success: (...args: unknown[]) => mockToastSuccess(...args),
    error: (...args: unknown[]) => mockToastError(...args),
  },
}));

jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  useNavigation: () => ({ go: mockGo }),
}));

interface MockResponseInit {
  ok: boolean;
  status: number;
  statusText: string;
  json: () => Promise<unknown>;
}

function mockResponse(init: MockResponseInit): Response {
  return init as unknown as Response;
}

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
  render(<SlackTokensForm isUpdate={false} initialValues={emptyBot} />);

  await user.type(screen.getByLabelText(/name this slack bot/i), "Support");
  await user.type(screen.getByLabelText(/slack bot token/i), "xoxb-1");
  await user.type(screen.getByLabelText(/slack app token/i), "xapp-1");
  await user.click(screen.getByRole("button", { name: /create/i }));
}

test("shows an error toast when the error response is not JSON", async () => {
  // POST /api/manage/admin/slack-app/bots answered by a proxy HTML page
  fetchSpy.mockResolvedValueOnce(
    mockResponse({
      ok: false,
      status: 502,
      statusText: "Bad Gateway",
      json: async () => {
        throw new SyntaxError("Unexpected token '<'");
      },
    })
  );

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - Bad Gateway"
    );
  });
  expect(mockToastSuccess).not.toHaveBeenCalled();
});

test("shows a generic error when the body has no detail and no status text", async () => {
  // POST /api/manage/admin/slack-app/bots over HTTP/2 (no status text)
  fetchSpy.mockResolvedValueOnce(
    mockResponse({
      ok: false,
      status: 500,
      statusText: "",
      json: async () => ({}),
    })
  );

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - An unknown error occurred"
    );
  });
});

test("maps an invalid bot token detail to the translated message", async () => {
  // POST /api/manage/admin/slack-app/bots rejected by token validation
  fetchSpy.mockResolvedValueOnce(
    mockResponse({
      ok: false,
      status: 400,
      statusText: "Bad Request",
      json: async () => ({ detail: "Invalid bot token: invalid_auth" }),
    })
  );

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockToastError).toHaveBeenCalledWith(
      "Error creating Slack Bot - Slack Bot Token is invalid"
    );
  });
});

test("goes to the new bot page after a create", async () => {
  // POST /api/manage/admin/slack-app/bots returns the new bot
  fetchSpy.mockResolvedValueOnce(
    mockResponse({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ id: 7 }),
    })
  );

  await fillAndSubmitNewBot();

  await waitFor(() => {
    expect(mockGo).toHaveBeenCalledWith("/admin/bots/7");
  });
  expect(mockToastError).not.toHaveBeenCalled();
});
