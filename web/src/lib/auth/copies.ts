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
