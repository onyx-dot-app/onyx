export const GREETING_MESSAGES = [
  "What would you like to do today?",
  "How can I help?",
  "What are you working on?",
  "Hey! What's on your mind?",
  "What can I assist you with?",
  "Ready to help. What do you need?",
  "How may I assist you today?",
  "What's your question?",
  "Let's get started. What's up?",
  "What would you like to explore?",
];

export function getRandomGreeting(): string {
  return GREETING_MESSAGES[
    Math.floor(Math.random() * GREETING_MESSAGES.length)
  ];
}
