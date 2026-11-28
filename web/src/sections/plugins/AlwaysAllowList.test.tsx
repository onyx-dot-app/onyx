import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import AlwaysAllowList from "@/sections/plugins/AlwaysAllowList";
import messages from "@/i18n/messages/en.json";
import {
  makeAction,
  mockFetch,
  requestBody,
} from "@tests/setup/integrationTestUtils";
import type { MemberActionPolicies } from "@/lib/integrations/types";

const URL_POLICIES = "/api/action-policies/integration/1";
const switchName = messages.plugins.member.alwaysAllow.switch.label.replace(
  "{name}",
  "List issues"
);

function policies(
  usersCanSave: boolean,
  userPolicy: "allow" | null
): MemberActionPolicies {
  return {
    users_can_save_always_allow: usersCanSave,
    actions: [
      {
        ...makeAction({ effective_admin_policy: "ask" }),
        user_policy: userPolicy,
      },
    ],
  };
}

afterEach(() => jest.restoreAllMocks());

test("lets a user clear a saved grant after the admin stops new grants", async () => {
  const fetchMock = mockFetch({
    [URL_POLICIES]: policies(false, "allow"),
    [`PUT ${URL_POLICIES}`]: policies(false, null),
  });
  const u = setupUser();
  render(<AlwaysAllowList integrationId={1} />);

  const toggle = await screen.findByRole("switch", { name: switchName });
  expect(toggle).toBeChecked();
  expect(toggle).toBeEnabled();
  await u.click(toggle);
  await waitFor(() =>
    expect(requestBody(fetchMock, "PUT", URL_POLICIES)).toEqual({
      actions: { list_issues: null },
    })
  );
});

test("offers no new grant when the admin stops new grants", async () => {
  mockFetch({ [URL_POLICIES]: policies(false, null) });
  render(<AlwaysAllowList integrationId={1} />);

  await screen.findByText("List issues");
  expect(
    screen.queryByRole("switch", { name: switchName })
  ).not.toBeInTheDocument();
});
