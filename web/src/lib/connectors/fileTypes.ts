import { FileTypeCategory } from "./types";
import type { FileTypeDefinition } from "./types";

export const FILE_TYPE_DEFINITIONS: Record<
  FileTypeCategory,
  FileTypeDefinition
> = {
  [FileTypeCategory.SHAREPOINT_PFX_FILE]: {
    category: FileTypeCategory.SHAREPOINT_PFX_FILE,
    validation: {
      maxSizeKB: 10,
      allowedExtensions: [".pfx"],
    },
    description:
      "Please upload the .pfx file containing the private key of the app registration. The file size must be under 10KB.",
  },
};

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
