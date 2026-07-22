import { SvgGlobe, SvgUserKey } from "@opal/icons";
import { SvgGoogle } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import { toast } from "@opal/layouts";
import { SSOProviderType } from "@/lib/sso/interfaces";

interface SSOProviderDetail {
  label: string;
  icon: IconFunctionComponent;
  description: string;
}

export const SSO_PROVIDER_DETAILS: Record<SSOProviderType, SSOProviderDetail> =
  {
    GOOGLE_OAUTH: {
      label: "Google",
      icon: SvgGoogle,
      description: "Use Google as the identity provider.",
    },
    OIDC: {
      label: "OIDC",
      icon: SvgGlobe,
      description: "Connect a generic OpenID Connect provider.",
    },
    SAML: {
      label: "SAML",
      icon: SvgUserKey,
      description: "Connect a SAML identity provider.",
    },
  };

// Provider types the create modal offers, in dropdown order.
export const CREATABLE_SSO_PROVIDER_TYPES: SSOProviderType[] = [
  "GOOGLE_OAUTH",
  "OIDC",
  "SAML",
];

export type SSOConfigFieldKind = "text" | "textarea" | "password";

// One entry per key in a provider type's backend config model. `name` must
// match the backend config field exactly, since values are sent as
// config.<name>.
export interface SSOConfigField {
  name: string;
  label: string;
  kind: SSOConfigFieldKind;
  description: string;
  optional?: boolean;
  placeholder?: string;
}

const CLIENT_ID_FIELD: SSOConfigField = {
  name: "client_id",
  label: "Client ID",
  kind: "text",
  description: "The OAuth client ID from your provider's console.",
  placeholder: "Client ID",
};
const CLIENT_SECRET_FIELD: SSOConfigField = {
  name: "client_secret",
  label: "Client Secret",
  kind: "password",
  description: "The OAuth client secret. Stored encrypted.",
  placeholder: "Client secret",
};

export const CONFIG_FIELDS_BY_TYPE: Record<SSOProviderType, SSOConfigField[]> =
  {
    GOOGLE_OAUTH: [CLIENT_ID_FIELD, CLIENT_SECRET_FIELD],
    OIDC: [
      CLIENT_ID_FIELD,
      CLIENT_SECRET_FIELD,
      {
        name: "openid_config_url",
        label: "OpenID Configuration URL",
        kind: "text",
        description: "The IdP's OpenID Connect discovery document URL.",
        placeholder: "https://example.com/.well-known/openid-configuration",
      },
    ],
    SAML: [
      {
        name: "idp_entity_id",
        label: "IdP Entity ID",
        kind: "text",
        description: "The identity provider's entity ID (issuer).",
        placeholder: "https://idp.example.com/entity",
      },
      {
        name: "idp_sso_url",
        label: "IdP SSO URL",
        kind: "text",
        description: "The IdP endpoint that receives sign-in requests.",
        placeholder: "https://idp.example.com/sso",
      },
      {
        name: "idp_x509_cert",
        label: "IdP X.509 Certificate",
        kind: "textarea",
        description:
          "The IdP's signing certificate, used to verify assertions.",
        placeholder: "-----BEGIN CERTIFICATE-----",
      },
      {
        name: "sp_entity_id",
        label: "SP Entity ID",
        kind: "text",
        description: "This instance's entity ID, registered with the IdP.",
        placeholder: "onyx",
      },
      {
        name: "sp_x509_cert",
        label: "SP X.509 Certificate",
        kind: "textarea",
        description:
          "Only if this instance signs requests or decrypts assertions.",
        optional: true,
        placeholder: "-----BEGIN CERTIFICATE-----",
      },
      {
        name: "sp_private_key",
        label: "SP Private Key",
        kind: "password",
        description:
          "Private key paired with the SP certificate. Stored encrypted.",
        optional: true,
        placeholder: "-----BEGIN PRIVATE KEY-----",
      },
      {
        name: "email_attribute",
        label: "Email Attribute",
        kind: "text",
        description:
          "SAML attribute holding the user's email. Defaults to common keys.",
        optional: true,
        placeholder: "email",
      },
    ],
  };

export async function copyRedirectUri(redirectUri: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(redirectUri);
    toast.success("Redirect URI copied");
  } catch {
    toast.error("Could not copy");
  }
}
