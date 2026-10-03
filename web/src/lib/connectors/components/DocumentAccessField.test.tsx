import { render, screen, waitFor } from "@tests/setup/test-utils";
import { Formik } from "formik";
import DocumentAccessField from "@/lib/connectors/components/DocumentAccessField";
import {
  ConfigurableSources,
  ValidSources,
} from "@/lib/connectors/types/source";

jest.mock("@/lib/permissions/hooks", () => ({
  usePermissionAuthority: jest.fn(),
}));
jest.mock("@/hooks/useTierAtLeast", () => ({
  useTierAtLeast: jest.fn(),
}));
jest.mock("@/components/admin/connectors/AutoSyncOptions", () => ({
  AutoSyncOptions: () => null,
}));
jest.mock("@/lib/connectors/components/GroupShareList", () => ({
  __esModule: true,
  default: () => null,
}));

const { usePermissionAuthority } = jest.requireMock("@/lib/permissions/hooks");
const { useTierAtLeast } = jest.requireMock("@/hooks/useTierAtLeast");

function renderForm(connector: ConfigurableSources) {
  return render(
    <Formik
      initialValues={{
        access_type: "public",
        groups: [],
        data_access_group_ids: [],
      }}
      onSubmit={() => {}}
    >
      {({ values }) => (
        <>
          <DocumentAccessField connector={connector} />
          <output data-testid="access-type">{values.access_type}</output>
        </>
      )}
    </Formik>
  );
}

describe("DocumentAccessField", () => {
  beforeEach(() => {
    useTierAtLeast.mockReturnValue(true);
    usePermissionAuthority.mockReturnValue({
      isGlobalHolder: true,
      isScopedManager: false,
    });
  });

  it("leaves public alone for a user who is still offered it", () => {
    renderForm(ValidSources.Web as ConfigurableSources);

    expect(screen.getByTestId("access-type")).toHaveTextContent("public");
  });

  it("moves a scoped manager off public, which they are not offered", async () => {
    usePermissionAuthority.mockReturnValue({
      isGlobalHolder: false,
      isScopedManager: true,
    });

    renderForm(ValidSources.Web as ConfigurableSources);

    await waitFor(() =>
      expect(screen.getByTestId("access-type")).toHaveTextContent("private")
    );
  });

  it("defaults to auto sync on a source that supports it", async () => {
    renderForm(ValidSources.GoogleDrive as ConfigurableSources);

    await waitFor(() =>
      expect(screen.getByTestId("access-type")).toHaveTextContent("sync")
    );
  });

  it("prefers auto sync over private on a source that supports it", async () => {
    usePermissionAuthority.mockReturnValue({
      isGlobalHolder: false,
      isScopedManager: true,
    });

    renderForm(ValidSources.GoogleDrive as ConfigurableSources);

    await waitFor(() =>
      expect(screen.getByTestId("access-type")).toHaveTextContent("sync")
    );
  });
});
