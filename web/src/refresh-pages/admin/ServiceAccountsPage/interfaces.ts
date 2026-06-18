import { UserRole } from "@/lib/types";
import { SvgUserManage, SvgUser, SvgLock } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export const DISCORD_SERVICE_API_KEY_NAME = "discord-bot-service";

// Roles assignable to a service account, shared by the Account Type column and
// the Groups & Roles modal so the option list lives in one place.
export const SERVICE_ACCOUNT_ROLE_OPTIONS: {
  role: UserRole;
  icon: IconFunctionComponent;
  description: string;
}[] = [
  {
    role: UserRole.ADMIN,
    icon: SvgUserManage,
    description: "Unrestricted admin access to all endpoints.",
  },
  {
    role: UserRole.BASIC,
    icon: SvgUser,
    description: "Standard user-level access to non-admin endpoints.",
  },
  {
    role: UserRole.LIMITED,
    icon: SvgLock,
    description:
      "For agents: chat posting and read-only access to other endpoints.",
  },
];

export interface APIKey {
  api_key_id: number;
  api_key_display: string;
  api_key: string | null;
  api_key_name: string | null;
  api_key_role: UserRole;
  user_id: string;
}

export interface APIKeyArgs {
  name?: string;
  role: UserRole;
}
