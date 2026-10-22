import englishMessages from "@/i18n/messages/en.json";
import {
  connectorConfigs,
  translateConfiguration,
} from "@/lib/connectors/connectors";
import type { CredentialValues } from "@/lib/credentials/types";

/** The message at a dotted path under `admin.connectorsList`, if any. */
function message(key: string): unknown {
  return key
    .split(".")
    .reduce<unknown>(
      (node, part) =>
        typeof node === "object" && node !== null
          ? (node as Record<string, unknown>)[part]
          : undefined,
      englishMessages.admin.connectorsList
    );
}

// Function-valued copy picks a key by the credential's kind.
const CREDENTIALS: (CredentialValues | null)[] = [
  null,
  { credential_json: { google_tokens: "tokens" } },
  { credential_json: { google_service_account_key: "key" } },
];

describe("connector form copy", () => {
  it.each(Object.keys(connectorConfigs))(
    "%s: every copy key is an English message",
    (source) => {
      const missing: string[] = [];
      const config = translateConfiguration(
        connectorConfigs[source as keyof typeof connectorConfigs],
        (key) => {
          if (typeof message(key) !== "string") missing.push(key);
          return key;
        }
      );
      // Function-valued copy resolves its key only when called.
      for (const field of [...config.values, ...config.advanced_values]) {
        const fields =
          field.type === "tab"
            ? field.tabs.flatMap((tab) => tab.fields)
            : [field];
        for (const f of [field, ...fields]) {
          for (const text of [f.label, f.description]) {
            if (typeof text === "function") {
              CREDENTIALS.forEach((credential) => text(credential));
            }
          }
        }
      }
      expect(missing).toEqual([]);
    }
  );
});
