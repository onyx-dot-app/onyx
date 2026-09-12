import type { useTranslations } from "next-intl";
import { SvgGlobe, SvgUserKey } from "@opal/icons";
import { SvgGoogle } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import { toast } from "@opal/layouts";
import { SSOProviderType } from "@/lib/sso/interfaces";

export type SSOTranslate = ReturnType<
  typeof useTranslations<"admin.ssoProviders">
>;
export type SSOMessageKey = Parameters<SSOTranslate>[0];

interface SSOProviderDetail {
  label: string;
  icon: IconFunctionComponent;
  descriptionKey: SSOMessageKey;
}

export const SSO_PROVIDER_DETAILS: Record<SSOProviderType, SSOProviderDetail> =
  {
    GOOGLE_OAUTH: {
      label: "Google",
      icon: SvgGoogle,
      descriptionKey: "providerTypes.googleOauth.description",
    },
    OIDC: {
      label: "OIDC",
      icon: SvgGlobe,
      descriptionKey: "providerTypes.oidc.description",
    },
    SAML: {
      label: "SAML",
      icon: SvgUserKey,
      descriptionKey: "providerTypes.saml.description",
    },
  };

// Provider types the create modal offers, in dropdown order.
export const CREATABLE_SSO_PROVIDER_TYPES: SSOProviderType[] = [
  "GOOGLE_OAUTH",
  "OIDC",
  "SAML",
];

export type SSOConfigFieldKind =
  | "text"
  | "textarea"
  | "password"
  | "switch"
  | "chips";

// One entry per admin-editable key in a provider type's backend config model.
// `name` must match the backend config field exactly, since values are sent
// as config.<name>. The user-facing text lives in "admin.ssoProviders".
export interface SSOConfigField {
  name: string;
  labelKey: SSOMessageKey;
  kind: SSOConfigFieldKind;
  descriptionKey: SSOMessageKey;
  optional?: boolean;
  placeholderKey?: SSOMessageKey;
  // URLs, PEM markers and ids are not translated.
  placeholder?: string;
  // Value a "switch" field starts at when the stored config has no key for
  // it yet (a row saved before the field existed, or a brand-new provider).
  // Must match the backend model's default so re-saving an untouched
  // provider round-trips its value instead of silently overriding it.
  switchDefault?: boolean;
}

const CLIENT_ID_FIELD: SSOConfigField = {
  name: "client_id",
  labelKey: "configFields.clientId.label",
  kind: "text",
  descriptionKey: "configFields.clientId.description",
  placeholderKey: "configFields.clientId.placeholder",
};
const CLIENT_SECRET_FIELD: SSOConfigField = {
  name: "client_secret",
  labelKey: "configFields.clientSecret.label",
  kind: "password",
  descriptionKey: "configFields.clientSecret.description",
  placeholderKey: "configFields.clientSecret.placeholder",
};
const PKCE_FIELD: SSOConfigField = {
  name: "pkce_enabled",
  labelKey: "configFields.pkceEnabled.label",
  kind: "switch",
  descriptionKey: "configFields.pkceEnabled.description",
};
const SCOPES_FIELD: SSOConfigField = {
  name: "scopes",
  labelKey: "configFields.scopes.label",
  kind: "chips",
  optional: true,
  descriptionKey: "configFields.scopes.description",
  placeholderKey: "configFields.scopes.placeholder",
};

export const CONFIG_FIELDS_BY_TYPE: Record<SSOProviderType, SSOConfigField[]> =
  {
    GOOGLE_OAUTH: [
      CLIENT_ID_FIELD,
      CLIENT_SECRET_FIELD,
      PKCE_FIELD,
      SCOPES_FIELD,
    ],
    OIDC: [
      CLIENT_ID_FIELD,
      CLIENT_SECRET_FIELD,
      {
        name: "openid_config_url",
        labelKey: "configFields.openidConfigUrl.label",
        kind: "text",
        descriptionKey: "configFields.openidConfigUrl.description",
        placeholder: "https://example.com/.well-known/openid-configuration",
      },
      {
        name: "require_verified_email",
        labelKey: "configFields.requireVerifiedEmail.label",
        kind: "switch",
        descriptionKey: "configFields.requireVerifiedEmail.description",
      },
      PKCE_FIELD,
      SCOPES_FIELD,
    ],
    SAML: [
      {
        name: "idp_entity_id",
        labelKey: "configFields.idpEntityId.label",
        kind: "text",
        descriptionKey: "configFields.idpEntityId.description",
        placeholder: "https://idp.example.com/entity",
      },
      {
        name: "idp_sso_url",
        labelKey: "configFields.idpSsoUrl.label",
        kind: "text",
        descriptionKey: "configFields.idpSsoUrl.description",
        placeholder: "https://idp.example.com/sso",
      },
      {
        name: "idp_x509_cert",
        labelKey: "configFields.idpX509Cert.label",
        kind: "textarea",
        descriptionKey: "configFields.idpX509Cert.description",
        placeholder: "-----BEGIN CERTIFICATE-----",
      },
      {
        name: "sp_entity_id",
        labelKey: "configFields.spEntityId.label",
        kind: "text",
        descriptionKey: "configFields.spEntityId.description",
        placeholder: "onyx",
      },
      {
        name: "sp_x509_cert",
        labelKey: "configFields.spX509Cert.label",
        kind: "textarea",
        descriptionKey: "configFields.spX509Cert.description",
        optional: true,
        placeholder: "-----BEGIN CERTIFICATE-----",
      },
      {
        name: "sp_private_key",
        labelKey: "configFields.spPrivateKey.label",
        kind: "password",
        descriptionKey: "configFields.spPrivateKey.description",
        optional: true,
        placeholder: "-----BEGIN PRIVATE KEY-----",
      },
      {
        name: "email_attribute",
        labelKey: "configFields.emailAttribute.label",
        kind: "text",
        descriptionKey: "configFields.emailAttribute.description",
        optional: true,
        placeholderKey: "configFields.emailAttribute.placeholder",
      },
      {
        name: "request_authn_context",
        label: "Require Exact-Match Authentication Context",
        kind: "switch",
        description:
          "Request PasswordProtectedTransport specifically at sign-in. " +
          "Turn off for IdPs that enforce MFA or FIDO2 (such as Microsoft " +
          "Entra ID with Conditional Access), which reject the exact match " +
          "with AADSTS75011.",
        // Matches SAMLProviderConfig.request_authn_context's backend default,
        // so a provider saved before this field existed keeps behaving the
        // same way the first time its form is opened and re-saved.
        switchDefault: true,
      },
    ],
  };

export async function copyRedirectUri(
  redirectUri: string,
  t: SSOTranslate
): Promise<void> {
  try {
    await navigator.clipboard.writeText(redirectUri);
    toast.success(t("copyRedirectUri.successToast"));
  } catch {
    toast.error(t("copyRedirectUri.errorToast"));
  }
}
