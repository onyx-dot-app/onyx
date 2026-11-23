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

function stubRestrictions(restrictions: PlaygroundRestrictedFeature[]) {
  mockUseSettings.mockReturnValue({
    playground_restrictions: restrictions,
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
  expect(screen.getByText("Enterprise Plan")).toBeInTheDocument();
  // The markdown source, since react-markdown is stubbed above.
  expect(
    screen.getByText(
      /\[Talk to sales\]\(https:\/\/www\.onyx\.app\/contact-sales\)/
    )
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add provider" })).toBeDisabled();
  // Inert covers what a disabled fieldset does not: a focusable card with a
  // key handler cannot take focus, so its editor cannot open.
  expect(screen.getByTestId("provider-card").closest("[inert]")).not.toBeNull();
});

test("a switched-off feature shows the notice without a plan badge", () => {
  stubRestrictions([PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS]);
  render(
    <PlaygroundRestrictedPage
      featureKey={PlaygroundRestrictedFeature.SERVICE_ACCOUNT_KEYS}
    >
      <Page />
    </PlaygroundRestrictedPage>
  );

  expect(screen.getByText("Playground Limit")).toBeInTheDocument();
  expect(screen.queryByText("Enterprise Plan")).not.toBeInTheDocument();
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
