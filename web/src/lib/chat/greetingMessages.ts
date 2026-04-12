import type { useTranslations } from "next-intl";

type TranslationFunction = ReturnType<typeof useTranslations<"chat">>;

/** @deprecated Use getGreetingMessages(t) instead for i18n support */
export const GREETING_MESSAGES = ["How can I help?", "Let's get started."];

export function getGreetingMessages(
  t: TranslationFunction
): string[] {
  return [t("greeting.howCanIHelp"), t("greeting.letsGetStarted")];
}

export function getRandomGreeting(t: TranslationFunction): string {
  const messages = getGreetingMessages(t);
  return messages[Math.floor(Math.random() * messages.length)] as string;
}
