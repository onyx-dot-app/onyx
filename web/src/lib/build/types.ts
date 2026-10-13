export interface FilePreviewResult<T> {
  identity: string;
  data?: T;
  error?: Error;
}
