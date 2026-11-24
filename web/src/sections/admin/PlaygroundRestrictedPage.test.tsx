import { render, screen } from "@tests/setup/test-utils";
import PlaygroundRestrictedPage from "@/sections/admin/PlaygroundRestrictedPage";
import { PlaygroundRestrictedFeature } from "@/lib/playground/types";
import { useSettings } from "@/lib/settings/hooks";

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: jest.fn(),
}));

// The notice renders as Opal markdown. Under Jest, react-markdown's default
// export loads as a module object, so render the source text as is.
jest.mock("react-markdown", () => ({
  __esModule: true,
  default: ({ children }: { children?: string }) => children ?? null,
}));

const mockUseSettings = useSettings as jest.MockedFunction<typeof useSettings>;

// `arrived` false stands for settings that have not come back yet: the
// hook then serves the defaults, which carry no list.
function stubRestrictions(
  restrictions: PlaygroundRestrictedFeature[],
  arrived = true
) {
  mockUseSettings.mockReturnValue({
    isLoading: !arrived,
    playground_restrictions: arrived ? restrictions : undefined,
  } as ReturnType<typeof useSettings>);
}

function Page() {
  return (
    <div>
      <button type="button">Add provider</button>
      {/* A card that opens an editor on Enter, like the provider cards. */}
      <div role="button" tabIndex={0} data-testid="provider-card">
        OpenAI
      </div>
    </div>
  );
}

test("a restricted page shows the notice and disables its controls", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SSO]);
  render(
    <PlaygroundRestrictedPage featureKey={PlaygroundRestrictedFeature.SSO}>
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.getByText("Playground Limit")).toBeInTheDocument();
  // The markdown source, since react-markdown is stubbed above.
  expect(
    screen.getByText(
      /Enterprise feature.*\[Talk to sales\]\(https:\/\/www\.onyx\.app\/contact-sales\)/
    )
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add provider" })).toBeDisabled();
  // Inert covers what a disabled fieldset does not: a focusable card with a
  // key handler cannot take focus, so its editor cannot open.
  expect(screen.getByTestId("provider-card").closest("[inert]")).not.toBeNull();
});

test("a switched-off feature says it is off on the playground", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS]);
  render(
    <PlaygroundRestrictedPage
      featureKey={PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS}
    >
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.getByText("Playground Limit")).toBeInTheDocument();
  expect(
    screen.getByText(/switched off on the playground/)
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add provider" })).toBeDisabled();
});

test("an unrestricted page renders as it is", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SSO]);
  render(
    <PlaygroundRestrictedPage featureKey={PlaygroundRestrictedFeature.SCIM}>
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.queryByText("Playground Limit")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add provider" })).toBeEnabled();
  expect(screen.getByTestId("provider-card").closest("[inert]")).toBeNull();
});

test("a page with a feature key waits for the core settings before it is live", () => {
  stubRestrictions([], false);
  render(
    <PlaygroundRestrictedPage featureKey={PlaygroundRestrictedFeature.SSO}>
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.queryByRole("button", { name: "Add provider" })).toBeNull();
  expect(screen.queryByText("Playground Limit")).not.toBeInTheDocument();
});

test("a branding outage does not hold a page whose core settings loaded", () => {
  mockUseSettings.mockReturnValue({
    error: new Error("branding unavailable"),
    playground_restrictions: [PlaygroundRestrictedFeature.SSO],
  } as ReturnType<typeof useSettings>);
  render(
    <PlaygroundRestrictedPage featureKey={PlaygroundRestrictedFeature.SSO}>
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.getByText("Playground Limit")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add provider" })).toBeDisabled();
});

test("a page without a feature key renders while the settings load", () => {
  stubRestrictions([], false);
  render(
    <PlaygroundRestrictedPage featureKey={undefined}>
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.getByRole("button", { name: "Add provider" })).toBeEnabled();
});

test("a page without a feature key renders as it is on the playground", () => {
  stubRestrictions([
    PlaygroundRestrictedFeature.SSO,
    PlaygroundRestrictedFeature.SCIM,
  ]);
  render(
    <PlaygroundRestrictedPage featureKey={undefined}>
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.queryByText("Playground Limit")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add provider" })).toBeEnabled();
});
