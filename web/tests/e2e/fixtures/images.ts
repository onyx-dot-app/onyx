// 50x50 black/white checkered PNG — clearly a test artifact. The bytes pass
// PIL validation (which upload endpoints run to reject malformed images), so
// it works for any test that needs a real, small, valid image upload.
export const CHECKERED_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAADIAAAAyCAIAAACRXR/mAAAAVElEQVR42u3WwQkAIAwDQOP+O9cN+lJUuHylcFApyWhTVc1rkkOzczwZLCwsrN9YuXXH+1lLxMLCwtpz5XV5fwsLC0uX1+WxsLCwdHldHgsLC+uxLK9hJFqMAN43AAAAAElFTkSuQmCC",
  "base64"
);
