import k from "@/i18n/keys";

export const getErrorMsg = async (
  response: Response,
  t?: (key: string) => string
) => {
  if (response.ok) {
    return null;
  }
  const responseJson = await response.json();
  return (
    responseJson.message ||
    responseJson.detail ||
    (t ? t(k.UNKNOWN_ERROR) : "Unknown error")
  );
};
