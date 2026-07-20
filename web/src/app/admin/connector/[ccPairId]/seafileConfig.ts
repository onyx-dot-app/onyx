import * as Yup from "yup";

export interface SeafileConnectorConfig {
  base_url: string;
  repo_ids: string[];
  path_prefixes: string[];
  allowed_extensions: string[];
  max_file_size_bytes: number;
}

export const SEAFILE_SUPPORTED_EXTENSIONS = [
  ".conf",
  ".csv",
  ".docx",
  ".eml",
  ".epub",
  ".html",
  ".jpeg",
  ".jpg",
  ".json",
  ".log",
  ".markdown",
  ".md",
  ".mdx",
  ".pdf",
  ".png",
  ".pptx",
  ".sql",
  ".tsv",
  ".txt",
  ".webp",
  ".xlsm",
  ".xlsx",
  ".xml",
  ".yaml",
  ".yml",
] as const;

const supportedExtensionSet = new Set<string>(SEAFILE_SUPPORTED_EXTENSIONS);

function uniqueNonEmpty(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }

  return Array.from(
    new Set(
      values
        .map((value) => String(value).trim())
        .filter((value) => value.length > 0)
    )
  );
}

function normalizePathPrefix(pathPrefix: string): string {
  const trimmed = pathPrefix.trim();
  if (!trimmed || trimmed === "/") {
    return "/";
  }

  return `/${trimmed.replace(/^\/+/, "").replace(/\/+$/, "")}`;
}

function normalizeExtension(extension: string): string {
  const trimmed = extension.trim().toLowerCase();
  if (!trimmed) {
    return "";
  }

  return trimmed.startsWith(".") ? trimmed : `.${trimmed}`;
}

export function normalizeSeafileConnectorConfig(
  config: Partial<SeafileConnectorConfig>
): SeafileConnectorConfig {
  const pathPrefixes = uniqueNonEmpty(config.path_prefixes).map(
    normalizePathPrefix
  );

  return {
    base_url: String(config.base_url ?? "").trim(),
    repo_ids: uniqueNonEmpty(config.repo_ids),
    path_prefixes: pathPrefixes.length > 0 ? pathPrefixes : ["/"],
    allowed_extensions: Array.from(
      new Set(uniqueNonEmpty(config.allowed_extensions).map(normalizeExtension))
    ).filter((extension) => extension.length > 0),
    max_file_size_bytes: Number(config.max_file_size_bytes),
  };
}

export function seafileConfigEquals(
  left: Partial<SeafileConnectorConfig>,
  right: Partial<SeafileConnectorConfig>
): boolean {
  return (
    JSON.stringify(normalizeSeafileConnectorConfig(left)) ===
    JSON.stringify(normalizeSeafileConnectorConfig(right))
  );
}

export const SeafileConnectorConfigSchema: Yup.ObjectSchema<SeafileConnectorConfig> =
  Yup.object({
    base_url: Yup.string()
      .trim()
      .required("Base URL is required")
      .matches(/^https?:\/\//, "Base URL must start with http:// or https://"),
    repo_ids: Yup.array()
      .of(Yup.string().required())
      .test(
        "has-repo-id",
        "At least one library ID is required",
        (value) => uniqueNonEmpty(value).length > 0
      )
      .required(),
    path_prefixes: Yup.array().of(Yup.string().required()).required(),
    allowed_extensions: Yup.array()
      .of(Yup.string().required())
      .test(
        "has-extension",
        "At least one file extension is required",
        (value) => uniqueNonEmpty(value).length > 0
      )
      .test(
        "supported-extensions",
        "One or more extensions are not supported by the Seafile connector",
        (value) =>
          uniqueNonEmpty(value)
            .map(normalizeExtension)
            .every((extension) => supportedExtensionSet.has(extension))
      )
      .required(),
    max_file_size_bytes: Yup.number()
      .integer("Max file size must be an integer")
      .positive("Max file size must be greater than zero")
      .required("Max file size is required"),
  });
