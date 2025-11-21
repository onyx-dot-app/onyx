export const GREETING_MESSAGES = ["Comment puis-je aider ?", "Commençons !", "Bonjour, comment puis-je vous aider ?", "Qu'est-ce que vous voulez faire ?"];

export function getRandomGreeting(): string {
  return GREETING_MESSAGES[
    Math.floor(Math.random() * GREETING_MESSAGES.length)
  ] as string;
}
