const POWERPOINT_EXTENSION = /\.pptx?$/i;

export function isPowerPointPath(path: string): boolean {
  return POWERPOINT_EXTENSION.test(path);
}
