import { z } from "zod";

export const startSchema = z.object({
  type: z.literal("start"),
  allowWorkloadIdentity: z.boolean().default(false),
  config: z.object({
    model_provider: z.string(),
    model_name: z.string(),
    api_key: z.string().nullable(),
    api_base: z.string().nullable(),
    api_version: z.string().nullable(),
    deployment_name: z.string().nullable(),
    custom_config: z.record(z.string(), z.string()).nullable(),
    temperature: z.number(),
    max_input_tokens: z.number().positive(),
    reasoning_effort_default: z.string().nullable(),
    reasoning_effort_user_default: z.string().nullable(),
    reasoning_effort_max: z.string().nullable(),
  }),
  options: z.record(z.string(), z.unknown()),
  apiSurface: z.string().nullable(),
  reasoningEffort: z.string(),
  maxTurns: z.number().int().min(1).max(100),
  sessionId: z.string().nullable(),
  mockResponse: z.string().nullable().optional(),
});
export type Start = z.infer<typeof startSchema>;
export const historySchema = z.array(
  z.object({
    role: z.enum(["system", "developer", "user", "assistant", "tool"]),
    content: z
      .union([
        z.string(),
        z.array(
          z.object({
            type: z.string(),
            text: z.string().optional(),
            image_url: z.object({ url: z.string() }).optional(),
          }),
        ),
      ])
      .nullable()
      .optional(),
    tool_call_id: z.string().optional(),
    tool_calls: z
      .array(
        z.object({
          id: z.string(),
          function: z.object({
            name: z.string(),
            arguments: z.string(),
          }),
        }),
      )
      .optional(),
  }),
);
export const contextSchema = z.object({
  history: historySchema,
  tools: z.array(
    z.object({
      type: z.literal("function"),
      function: z.object({
        name: z.string(),
        description: z.string().optional(),
        parameters: z.record(z.string(), z.unknown()),
      }),
    }),
  ),
  toolChoice: z.enum(["auto", "none", "required"]),
});
export type PreparedContext = z.infer<typeof contextSchema>;
export interface Host {
  request(type: string, payload?: Record<string, unknown>): Promise<unknown>;
  send(event: Record<string, unknown>): void;
}
