"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { validateToolDefinition } from "@/lib/plugins/openapi/svc";
import {
  parseOpenApiSchema,
  type CheckedOpenApiSchema,
} from "@/lib/plugins/openapi/schema";

interface SchemaCheckResult {
  text: string;
  checked: CheckedOpenApiSchema | null;
  error: string | null;
}

export interface OpenApiSchemaCheck {
  /** The accepted schema, when it matches the current text. */
  checked: CheckedOpenApiSchema | null;
  /** Why the current text was rejected, if it was. */
  error: string | null;
  /** True while `check` runs. */
  checking: boolean;
  /** Checks the current text now and returns the accepted schema, or null. */
  check: () => Promise<CheckedOpenApiSchema | null>;
}

/**
 * Checks OpenAPI schema text with the server, 300ms after it stops changing.
 * Results for older text are ignored.
 */
export function useOpenApiSchemaCheck(
  text: string,
  invalidJsonMessage: string
): OpenApiSchemaCheck {
  const [result, setResult] = useState<SchemaCheckResult | null>(null);
  const [checking, setChecking] = useState(false);
  const request = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const run = useCallback(
    async (value: string): Promise<CheckedOpenApiSchema | null> => {
      const id = ++request.current;
      if (!value.trim()) {
        setResult(null);
        return null;
      }
      let definition;
      try {
        definition = parseOpenApiSchema(value);
      } catch {
        setResult({ text: value, checked: null, error: invalidJsonMessage });
        return null;
      }
      const response = await validateToolDefinition({ definition });
      if (id !== request.current) return null;
      if (response.error) {
        setResult({ text: value, checked: null, error: response.error });
        return null;
      }
      const checked = { text: value, definition, methods: response.data ?? [] };
      setResult({ text: value, checked, error: null });
      return checked;
    },
    [invalidJsonMessage]
  );

  useEffect(() => {
    timer.current = setTimeout(() => void run(text), 300);
    return () => {
      clearTimeout(timer.current);
      request.current += 1;
    };
  }, [text, run]);

  const check = useCallback(async () => {
    // A pending debounced run would supersede this one and void its result.
    clearTimeout(timer.current);
    setChecking(true);
    try {
      return await run(text);
    } finally {
      setChecking(false);
    }
  }, [run, text]);

  const current = result?.text === text ? result : null;
  return {
    checked: current?.checked ?? null,
    error: current?.error ?? null,
    checking,
    check,
  };
}
