import { SvgGlobe, SvgUserKey } from "@opal/icons";
import { SvgGoogle } from "@opal/logos";
import type { IconFunctionComponent } from "@opal/types";
import { toast } from "@/hooks/useToast";
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

// Provider types an admin can create today.
export const CREATABLE_SSO_PROVIDER_TYPES: SSOProviderType[] = [
  "GOOGLE_OAUTH",
  "OIDC",
  "SAML",
];

export async function copyRedirectUri(redirectUri: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(redirectUri);
    toast.success("Redirect URI copied");
  } catch {
    toast.error("Could not copy");
  }
}
