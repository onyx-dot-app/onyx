export enum FileTypeCategory {
  SHAREPOINT_PFX_FILE = "sharepoint_pfx_file",
}

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
