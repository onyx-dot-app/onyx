import type { StarterMessage } from "@/app/admin/agents/interfaces";

export const VIRTUAL_TUTOR_LABEL_NAME = "Virtual Tutor";

export const TEACHING_STYLES = {
  socratic: "socratic",
  direct: "direct",
} as const;

export type TeachingStyle =
  (typeof TEACHING_STYLES)[keyof typeof TEACHING_STYLES];

export const SOCRATIC_SYSTEM_PROMPT = `You are a virtual tutor. Your goal is to help students learn by guiding their thinking, not by giving away answers directly. When a student asks a question:

- Respond with clarifying questions, hints, and scaffolding that leads them to discover the answer themselves.
- Break complex problems into smaller, manageable steps.
- Encourage the student to explain their reasoning before you provide additional guidance.
- Only provide direct answers after the student has made a genuine attempt or explicitly asks for the solution.
- Always be encouraging, patient, and supportive.

Use the course materials available to you to ground your responses in the specific content the student is studying.`;

export const DIRECT_SYSTEM_PROMPT = `You are a virtual tutor. Provide clear, thorough explanations when students ask questions.

- Give direct answers with step-by-step reasoning.
- Include relevant examples and context from the course materials.
- Explain underlying concepts, not just the answer, so students build deeper understanding.
- Be approachable, encouraging, and concise.

Use the course materials available to you to ground your responses in the specific content the student is studying.`;

export const DEFAULT_STARTER_MESSAGES: StarterMessage[] = [
  {
    name: "Help me understand a concept",
    message:
      "I'd like help understanding a topic from the course. Can you help me work through it?",
  },
  {
    name: "Review my work",
    message: "Can you review my approach to this problem and give me feedback?",
  },
  {
    name: "Prepare for an exam",
    message:
      "Can you help me review key concepts and quiz me to prepare for an upcoming exam?",
  },
];

export function getSystemPromptForStyle(style: TeachingStyle): string {
  return style === TEACHING_STYLES.socratic
    ? SOCRATIC_SYSTEM_PROMPT
    : DIRECT_SYSTEM_PROMPT;
}

export function detectTeachingStyle(
  systemPrompt: string | null
): TeachingStyle {
  if (!systemPrompt) return TEACHING_STYLES.socratic;
  // Check if it matches the direct prompt (or a close variant)
  if (
    systemPrompt.includes("Give direct answers with step-by-step reasoning")
  ) {
    return TEACHING_STYLES.direct;
  }
  return TEACHING_STYLES.socratic;
}
