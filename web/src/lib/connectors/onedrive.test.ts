import {
  connectorConfigs,
  createConnectorInitialValues,
  getSelectedTabValue,
  getTabValueUpdates,
  type TabOption,
} from "@/lib/connectors/connectors";
import { credentialTemplates } from "@/lib/connectors/credentials";
import {
  FileTypeCategory,
  getFileTypeDefinitionForField,
} from "@/lib/connectors/fileTypes";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources, validAutoSyncSources } from "@/lib/types";

function oneDriveScopeField(): TabOption {
  const field = connectorConfigs[ValidSources.OneDrive].values[0];
  if (field?.type !== "tab") {
    throw new Error("OneDrive scope must use tabs");
  }
  return field;
}

describe("OneDrive connector metadata", () => {
  it("submits tenant-wide scope explicitly by default", () => {
    expect(createConnectorInitialValues(ValidSources.OneDrive)).toMatchObject({
      all_users: true,
      users: [],
    });
  });

  it("restores Specific scope from an existing config", () => {
    expect(
      getSelectedTabValue(oneDriveScopeField(), {
        all_users: false,
        users: ["owner@example.com"],
      })
    ).toBe("specific");
  });

  it("defaults existing configs without all_users to General", () => {
    expect(getSelectedTabValue(oneDriveScopeField(), { users: [] })).toBe(
      "general"
    );
  });

  it("clears users for General and submits false for Specific", () => {
    const field = oneDriveScopeField();

    expect(
      getTabValueUpdates(field, "general", {
        all_users: false,
        users: ["owner@example.com"],
      })
    ).toEqual({ all_users: true, users: [] });
    expect(
      getTabValueUpdates(field, "specific", {
        all_users: true,
        users: [],
      })
    ).toEqual({ all_users: false });
  });

  it("does not add selection state to tabs that do not opt in", () => {
    const initialValues = createConnectorInitialValues(
      ValidSources.GoogleDrive
    );

    expect(initialValues).not.toHaveProperty("indexing_scope");
    expect(initialValues).not.toHaveProperty("include_shared_drives");
  });

  it("defines both app-only credential methods", () => {
    expect(credentialTemplates[ValidSources.OneDrive]).toMatchObject({
      authentication_method: "client_secret",
      authMethods: [
        {
          value: "client_secret",
          fields: {
            onedrive_client_id: "",
            onedrive_directory_id: "",
            onedrive_client_secret: "",
          },
        },
        {
          value: "certificate",
          fields: {
            onedrive_client_id: "",
            onedrive_directory_id: "",
            onedrive_certificate_password: "",
            onedrive_private_key: null,
          },
        },
      ],
    });
  });

  it("uses the OneDrive logo and PKCS12 upload type without sync controls", () => {
    expect(getSourceMetadata(ValidSources.OneDrive).displayName).toBe(
      "OneDrive"
    );
    expect(getFileTypeDefinitionForField("onedrive_private_key")).toBe(
      FileTypeCategory.ONEDRIVE_PFX_FILE
    );
    expect(validAutoSyncSources).not.toContain(ValidSources.OneDrive);
  });
});
