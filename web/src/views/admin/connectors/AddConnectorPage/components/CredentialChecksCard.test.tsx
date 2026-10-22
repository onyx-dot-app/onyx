/**
 * Check rows read the result line the backend gives, with the guide's state
 * words as the fallback.
 */
import { render, screen } from "@tests/setup/test-utils";
import {
  type CheckLine,
  CheckLineGroups,
} from "@/views/admin/connectors/AddConnectorPage/components/CredentialChecksCard";

function line(
  overrides: Partial<CheckLine> & Pick<CheckLine, "state">
): CheckLine {
  return {
    capability: "indexing",
    check_id: "sign_in",
    display_name: "Sign in to Confluence",
    required: true,
    message: "",
    summary: null,
    description: null,
    remediation: null,
    docs_link: null,
    ...overrides,
  };
}

test("shows the result line in place of the state word or the raw message", () => {
  render(
    <CheckLineGroups
      lines={[
        line({ state: "passed", summary: "34 spaces visible" }),
        line({
          check_id: "auth",
          state: "failed",
          message: "Confluence rejected the credential (invalid_auth).",
          summary: "Sign-in rejected",
        }),
      ]}
    />
  );

  expect(screen.getByText("34 spaces visible")).toBeInTheDocument();
  expect(screen.getByText("Sign-in rejected")).toBeInTheDocument();
  expect(screen.queryByText("Successful")).not.toBeInTheDocument();
  expect(screen.queryByText(/invalid_auth/)).not.toBeInTheDocument();
});

test("reads incomplete and legacy indeterminate checks as Incomplete", () => {
  render(
    <CheckLineGroups
      lines={[
        line({ state: "incomplete" }),
        line({ check_id: "legacy", state: "indeterminate" }),
      ]}
    />
  );

  expect(screen.getByText("2 Incomplete")).toBeInTheDocument();
  expect(screen.getAllByText("Incomplete")).toHaveLength(2);
});
