import { credentialTemplates } from "@/lib/connectors/credentials";
import { getFileTypeDefinitionForField } from "@/lib/connectors/utils";
import { FileTypeCategory } from "@/lib/connectors/types";
import { getSourceMetadata } from "@/lib/sources";
import { ValidSources, validAutoSyncSources } from "@/lib/types";

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
});
