import {
  createConnectorInitialValues,
  createConnectorValidationSchema,
} from "@/lib/connectors/utils";
import { ValidSources } from "@/lib/connectors/types/source";

const messages = {
  stringPairEmptyKey: "Key cannot be empty",
  stringPairDuplicateKey: "Duplicate key",
};

function webValues(urlRewrites: Record<string, string>[]) {
  return {
    ...createConnectorInitialValues(ValidSources.Web),
    name: "web",
    base_url: "https://docs.example.com",
    url_rewrites: urlRewrites,
  };
}

function validate(urlRewrites: Record<string, string>[]) {
  return createConnectorValidationSchema(
    ValidSources.Web,
    false,
    messages
  ).validateAt("url_rewrites", webValues(urlRewrites));
}

test("URL rewrites with distinct source prefixes pass", async () => {
  await expect(
    validate([
      { source: "https://mirror.example.com", target: "https://a.example.com" },
      { source: "https://cache.example.com", target: "https://b.example.com" },
    ])
  ).resolves.toBeTruthy();
});

test("a URL rewrite without a source prefix fails", async () => {
  await expect(
    validate([{ source: " ", target: "https://a.example.com" }])
  ).rejects.toThrow("Key cannot be empty");
});

test("two URL rewrites with the same source prefix fail", async () => {
  await expect(
    validate([
      { source: "https://mirror.example.com", target: "https://a.example.com" },
      { source: "https://mirror.example.com", target: "https://b.example.com" },
    ])
  ).rejects.toThrow("Duplicate key");
});
