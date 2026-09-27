import { credentialTemplates } from "@/lib/connectors/credentials";
import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
  getFileTypeDefinitionForField,
} from "@/lib/connectors/utils";
import { FileTypeCategory, OneDriveScope } from "@/lib/connectors/types";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources, validAutoSyncSources } from "@/lib/types";

const ONE_DRIVE_USERS_REQUIRED = "Add at least one user for Specific scope";

describe("OneDrive connector metadata", () => {
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
});
