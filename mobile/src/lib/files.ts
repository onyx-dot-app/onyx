const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "gif", "webp", "heic", "bmp"];

// Uppercase extension without the dot; "" when there's no usable extension.
export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  if (dot <= 0 || dot === name.length - 1) return "";
  return name.slice(dot + 1).toUpperCase();
}

export function isImageName(name: string): boolean {
  return IMAGE_EXTENSIONS.includes(extensionOf(name).toLowerCase());
}
