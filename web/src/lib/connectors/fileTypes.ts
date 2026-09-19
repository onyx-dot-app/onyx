export enum FileTypeCategory {
  SHAREPOINT_PFX_FILE = "sharepoint_pfx_file",
  ONEDRIVE_PFX_FILE = "onedrive_pfx_file",
}

const SHAREPOINT_PRIVATE_KEY_FIELD = "sp_private_key";
const ONEDRIVE_PRIVATE_KEY_FIELD = "onedrive_private_key";
const OUTLOOK_PRIVATE_KEY_FIELD = "outlook_private_key";
const TEAMS_PRIVATE_KEY_FIELD = "teams_private_key";
const TYPED_FILE_FIELDS = new Set([
  SHAREPOINT_PRIVATE_KEY_FIELD,
  ONEDRIVE_PRIVATE_KEY_FIELD,
  OUTLOOK_PRIVATE_KEY_FIELD,
  TEAMS_PRIVATE_KEY_FIELD,
]);

export interface FileValidationRule {
  maxSizeKB?: number;
  allowedExtensions?: string[];
  contentValidation?: (file: File) => Promise<boolean>;
}

export interface FileTypeDefinition {
  category: FileTypeCategory;
  validation?: FileValidationRule;
  description?: string;
}

export const FILE_TYPE_DEFINITIONS = {
  [FileTypeCategory.SHAREPOINT_PFX_FILE]: {
    category: FileTypeCategory.SHAREPOINT_PFX_FILE,
    validation: {
      maxSizeKB: 10,
      allowedExtensions: [".pfx"],
    },
    description:
      "Please upload the .pfx file containing the private key of the app registration. The file size must be under 10KB.",
  },
  [FileTypeCategory.ONEDRIVE_PFX_FILE]: {
    category: FileTypeCategory.ONEDRIVE_PFX_FILE,
    validation: {
      maxSizeKB: 10,
      allowedExtensions: [".pfx"],
    },
    description:
      "Please upload a .pfx file containing the private key for OneDrive. The file size must be under 10KB.",
  },
} satisfies Record<FileTypeCategory, FileTypeDefinition>;

export class TypedFile {
  constructor(
    public readonly file: File,
    public readonly typeDefinition: FileTypeDefinition,
    public readonly fieldKey: string
  ) {}

  async validate(): Promise<{ isValid: boolean; errors: string[] }> {
    const errors: string[] = [];
    const { validation } = this.typeDefinition;

    if (!validation) {
      return {
        isValid: true,
        errors: [],
      };
    }

    // Size validation
    if (validation.maxSizeKB && this.file.size > validation.maxSizeKB * 1024) {
      errors.push(`File size must not exceed ${validation.maxSizeKB}KB`);
    }

    // Extension validation
    if (validation.allowedExtensions) {
      const extension = this.file.name.toLowerCase().split(".").pop();
      if (
        !extension ||
        !validation.allowedExtensions.includes(`.${extension}`)
      ) {
        errors.push(
          `File must have one of these extensions: ${validation.allowedExtensions.join(
            ", "
          )}`
        );
      }
    }

    // Content validation
    if (validation.contentValidation) {
      try {
        const isContentValid = await validation.contentValidation(this.file);
        if (!isContentValid) {
          errors.push(`File content validation failed`);
        }
      } catch (error) {
        errors.push(
          `Content validation error: ${
            error instanceof Error ? error.message : "Unknown error"
          }`
        );
      }
    }

    return {
      isValid: errors.length === 0,
      errors,
    };
  }
}

export function createTypedFile(
  file: File,
  fieldKey: string,
  typeDefinitionKey: FileTypeCategory
): TypedFile {
  const typeDefinition = FILE_TYPE_DEFINITIONS[typeDefinitionKey];
  if (!typeDefinition) {
    throw new Error(`Unknown file type definition: ${typeDefinitionKey}`);
  }

  return new TypedFile(file, typeDefinition, fieldKey);
}

export function isTypedFileField(fieldKey: string): boolean {
  return TYPED_FILE_FIELDS.has(fieldKey);
}

// Get the appropriate file type definition for a field
export function getFileTypeDefinitionForField(
  fieldKey: string
): FileTypeCategory | null {
  if (fieldKey === ONEDRIVE_PRIVATE_KEY_FIELD) {
    return FileTypeCategory.ONEDRIVE_PFX_FILE;
  }
  if (TYPED_FILE_FIELDS.has(fieldKey)) {
    return FileTypeCategory.SHAREPOINT_PFX_FILE;
  }
  return null;
}
