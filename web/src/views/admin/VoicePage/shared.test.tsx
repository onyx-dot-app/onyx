import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { PointerEventsCheckLevel } from "@testing-library/user-event";
import { VoiceProviderSetupModal } from "@/views/admin/VoicePage/shared";
import { SWR_KEYS } from "@/lib/swr-keys";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ appName: "Onyx" }),
}));

afterEach(() => jest.restoreAllMocks());

it("sets up the shared Zoom credentials from Voice with voice validation", async () => {
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockImplementation(
      async () => new Response(JSON.stringify({ success: true }))
    );
  const onSuccess = jest.fn();
  const user = setupUser({ pointerEventsCheck: PointerEventsCheckLevel.Never });
  render(
    <VoiceProviderSetupModal
      providerType="zoom"
      existingProvider={null}
      mode="stt"
      onSuccess={onSuccess}
    />
  );
  expect(
    await screen.findByText("Connect Zoom AI Services")
  ).toBeInTheDocument();
  expect(screen.getByRole("dialog")).toHaveTextContent(
    "Use one connection for Zoom Scribe and Zoom AI Decisions. Changes apply to both."
  );
  await user.type(screen.getByLabelText("API Key"), "zoom-key");
  await user.type(screen.getByLabelText("API Secret"), "zoom-secret");
  await user.click(screen.getByRole("button", { name: "Connect" }));
  await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
  const testRequest = fetchSpy.mock.calls.find(
    ([url]) => url === `${SWR_KEYS.voiceProviders}/test`
  )?.[1];
  expect(JSON.parse(String(testRequest?.body))).toMatchObject({
    validation_mode: "voice",
    provider_type: "zoom",
    api_key: "zoom-key",
    api_secret: "zoom-secret",
  });
  const saveRequest = fetchSpy.mock.calls.find(
    ([url]) => url === SWR_KEYS.voiceProviders
  )?.[1];
  expect(JSON.parse(String(saveRequest?.body))).toMatchObject({
    validation_mode: "voice",
    provider_type: "zoom",
    activate_stt: true,
    activate_tts: false,
    custom_config: { language: "en-US" },
  });
  expect(
    fetchSpy.mock.calls.some(([url]) => url === SWR_KEYS.decisionModel)
  ).toBe(false);
});
