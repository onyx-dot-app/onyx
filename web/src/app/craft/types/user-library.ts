/**
 * Types for User Library - raw binary file uploads in Craft.
 */

export interface LibraryEntry {
  id: string; // document_id
  name: string;
  path: string;
  is_directory: boolean;
  file_size: number | null;
  mime_type: string | null;
  sync_enabled: boolean;
  created_at: string;
  children?: LibraryEntry[];
}

export interface CreateDirectoryRequest {
  name: string;
  parent_path: string;
}

export interface UploadResponse {
  entries: LibraryEntry[];
  total_uploaded: number;
  total_size_bytes: number;
}
