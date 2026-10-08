import { render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { Formik } from "formik";
import DocumentAccessField from "@/views/admin/connectors/AddConnectorPage/components/DocumentAccessField";
import {
  ConfigurableSources,
  ValidSources,
} from "@/lib/connectors/types/source";

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: () => ({
    isGlobalHolder: true,
    isScopedManager: false,
  }),
}));
jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: () => true,
}));
jest.mock("@/lib/hooks", () => ({
  useUserGroups: jest.fn(),
}));

const { useUserGroups } = jest.requireMock("@/lib/hooks");

const groupPicker = () =>
  screen.getByPlaceholderText(
    "Add groups to restrict access to this connector"
  );

// Mock scrollIntoView which is not available in jsdom
Element.prototype.scrollIntoView = jest.fn();

const GROUPS = [
  { id: 1, name: "Engineering", users: [{}, {}] },
  { id: 2, name: "Sales", users: [{}] },
];

/** A private Web connector: no Auto Sync, so Specific Groups shows. */
function renderPrivate() {
  return render(
    <Formik
      initialValues={{
        access_type: "private",
        groups: [],
        data_access_group_ids: [],
      }}
      onSubmit={() => {}}
    >
      {({ values }) => (
        <>
          <DocumentAccessField
            connector={ValidSources.Web as ConfigurableSources}
          />
          <output data-testid="data-access">
            {JSON.stringify(values.data_access_group_ids)}
          </output>
          <output data-testid="groups">{JSON.stringify(values.groups)}</output>
        </>
      )}
    </Formik>
  );
}

describe("DocumentAccessField Specific Groups", () => {
  beforeEach(() => {
    useUserGroups.mockReturnValue({
      data: GROUPS,
      isLoading: false,
      error: undefined,
    });
  });

  it("starts with no reader groups", () => {
    renderPrivate();

    expect(screen.getByTestId("data-access")).toHaveTextContent("[]");
  });

  it("puts a picked group in data_access_group_ids, not groups", async () => {
    const user = userEvent.setup({ delay: null });
    renderPrivate();

    await user.click(groupPicker());
    await user.click(await screen.findByRole("option", { name: /Sales/ }));

    await waitFor(() =>
      expect(screen.getByTestId("data-access")).toHaveTextContent("[2]")
    );
    expect(screen.getByTestId("groups")).toHaveTextContent("[]");
  });

  it("reports a failed group load and locks the picker", () => {
    useUserGroups.mockReturnValue({
      data: undefined,
      isLoading: false,
      error: "boom",
    });
    renderPrivate();

    expect(
      screen.getByText("Could not load groups. Reload the page to try again.")
    ).toBeInTheDocument();
    expect(groupPicker()).toBeDisabled();
  });
});
