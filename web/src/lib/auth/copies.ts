import { RichStr } from "@opal/types";
import { markdown } from "@opal/utils";

export const DEFAULT_LOGIN_SUBTITLE = "Your open source AI platform for work";

export function welcomeCardCopy(appName: string, subtitle?: string | null) {
  return {
    title: `Welcome to ${appName}`,
    description: subtitle?.trim() || DEFAULT_LOGIN_SUBTITLE,
  } as const;
}

export function backToLoginOrSignupCopy(
  signupUnavailable: boolean = false
): string | RichStr {
  return signupUnavailable
    ? markdown("Back to [Sign In](/auth/login)")
    : markdown(
        "Back to [Sign In](/auth/login) or [Create an Account](/auth/signup)"
      );
}
