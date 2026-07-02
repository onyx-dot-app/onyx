import { RichStr } from "@opal/types";
import { markdown } from "@opal/utils";

export function welcomeCardCopy(appName: string) {
  return {
    title: `Welcome to ${appName}`,
    description: "Your open source AI platform for work",
  } as const;
}

export function createAccountCardCopy(appName: string) {
  return {
    title: "Create account",
    description: `Get started with ${appName}`,
  } as const;
}

export function bottomPrompt(
  signupUnavailable: boolean = false
): string | RichStr {
  return signupUnavailable
    ? markdown("Back to [Sign In](/auth/login?autoRedirectToSignup=false)")
    : markdown(
        "Back to [Sign In](/auth/login) or [Create an Account](/auth/signup)"
      );
}
