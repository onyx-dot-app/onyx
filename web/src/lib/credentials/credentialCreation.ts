import { OAuthDetails } from "@/lib/connectors/credentials";

export enum CredentialCreationMethod {
  OAuth = "oauth",
  Manual = "manual",
}

export function getCredentialCreationMethods(
  details?: OAuthDetails
): CredentialCreationMethod[] {
  if (!details) {
    return [CredentialCreationMethod.Manual];
  }

  const methods: CredentialCreationMethod[] = [];
  if (details.oauth_enabled) {
    methods.push(CredentialCreationMethod.OAuth);
  }
  if (details.supports_manual_credentials) {
    methods.push(CredentialCreationMethod.Manual);
  }
  return methods;
}

export function getCredentialCreationActionLabel(
  method: CredentialCreationMethod,
  sourceDisplayName: string,
  explicitMethod: boolean
): string {
  if (!explicitMethod) {
    return "Create New";
  }
  return method === CredentialCreationMethod.OAuth
    ? `Connect with ${sourceDisplayName}`
    : "Enter credentials manually";
}

export function shouldRedirectToOAuth(details: OAuthDetails): boolean {
  return details.additional_kwargs.length === 0;
}
