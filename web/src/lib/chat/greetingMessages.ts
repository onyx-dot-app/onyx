export const GREETING_MESSAGES = ["", ""];

export function getRandomGreeting(): string {
  return GREETING_MESSAGES[
    Math.floor(Math.random() * GREETING_MESSAGES.length)
  ] as string;
}
