import { AuthType } from "@/lib/constants";

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
  hasUsers: boolean;
  oauthEnabled: boolean;
}
