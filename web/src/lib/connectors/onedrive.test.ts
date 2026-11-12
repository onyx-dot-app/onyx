import englishMessages from "@/i18n/messages/en.json";
import { connectorConfigs } from "@/lib/connectors/connectors";
import {
  getSourceDocLink,
  getSourceMetadata,
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/utils";
import { CREDENTIAL_SPECS } from "@/lib/credentials/constants";
import { getCredentialFileType } from "@/lib/credentials/utils";
import { FileTypeCategory, OneDriveScope } from "@/lib/connectors/types";
import {
  ValidSources,
  validAutoSyncSources,
} from "@/lib/connectors/types/source";

const ONE_DRIVE_USERS_REQUIRED = "Add at least one user for Specific scope";

describe("OneDrive connector metadata", () => {
  it("defines both app-only credential methods", () => {
    expect(CREDENTIAL_SPECS[ValidSources.OneDrive].methods).toMatchObject([
      {
        value: "client_secret",
        fields: [
          "onedrive_client_id",
          "onedrive_directory_id",
          "onedrive_client_secret",
        ],
      },
      {
        value: "certificate",
        fields: [
          "onedrive_client_id",
          "onedrive_directory_id",
          "onedrive_certificate_password",
          "onedrive_private_key",
        ],
      },
    ]);
  });

  it("uses the OneDrive logo, PKCS12 upload type, and sync controls", () => {
    expect(getSourceMetadata(ValidSources.OneDrive).displayName).toBe(
      "OneDrive"
    );
    expect(getSourceDocLink(ValidSources.OneDrive)).toBe(
      "https://docs.onyx.app/admins/connectors/official/onedrive"
    );
    expect(getCredentialFileType("onedrive_private_key")).toBe(
      FileTypeCategory.ONEDRIVE_PFX_FILE
    );
    expect(validAutoSyncSources).toContain(ValidSources.OneDrive);
  });

  it("defaults to General scope and initializes nested users", () => {
    expect(createConnectorInitialValues(ValidSources.OneDrive)).toMatchObject({
      indexing_scope: OneDriveScope.General,
      users: [],
    });
  });

  it("accepts General scope without hidden field values", async () => {
    const values = {
      ...createConnectorInitialValues(ValidSources.OneDrive),
      name: "OneDrive",
      access_type: "public",
    };

    await expect(
      createConnectorValidationSchema(ValidSources.OneDrive).validate(values)
    ).resolves.toMatchObject({
      indexing_scope: OneDriveScope.General,
      users: [],
    });
  });

  it("requires at least one user for Specific scope", async () => {
    const schema = createConnectorValidationSchema(
      ValidSources.OneDrive,
      false,
      { oneDriveUsersRequired: ONE_DRIVE_USERS_REQUIRED }
    );

    await expect(
      schema.validateAt("users", {
        indexing_scope: OneDriveScope.Specific,
        users: [],
      })
    ).rejects.toThrow(ONE_DRIVE_USERS_REQUIRED);
    await expect(
      schema.validateAt("users", {
        indexing_scope: OneDriveScope.General,
        users: [],
      })
    ).resolves.toEqual([]);
  });

  it("links SharePoint personal-site guidance to OneDrive docs", () => {
    const sitesField = connectorConfigs[ValidSources.Sharepoint].values[0];
    if (!sitesField) {
      throw new Error("SharePoint sites field is required");
    }

    // The config holds the message key; the message links the OneDrive docs.
    expect(sitesField.description).toBe(
      "connectors.sharepoint.fields.sites.description"
    );
    expect(
      englishMessages.admin.connectorsList.connectors.sharepoint.fields.sites
        .description
    ).toContain(
      "[OneDrive connector]({docsAdminsPath}/connectors/official/onedrive)"
    );
  });
});
