import * as Yup from "yup";
import type { ApiTokenValue } from "@/lib/api-tokens/types";
import { isApiTokenValueEmpty } from "@/lib/api-tokens/utils";

/** Yup schema for an API key field. Pass a message to make the key required. */
export function apiTokenSchema(requiredMessage?: string) {
  const schema = Yup.mixed<ApiTokenValue>();
  if (!requiredMessage) return schema;
  return schema.test(
    "api-token-required",
    requiredMessage,
    (value) => value !== undefined && !isApiTokenValueEmpty(value)
  );
}
