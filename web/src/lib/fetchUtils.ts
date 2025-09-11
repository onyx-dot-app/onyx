import i18n from "@/i18n/init";
import k from "@/i18n/keys";

export const getErrorMsg = async (response: Response) => {
  if (response.ok) {
    return null;
  }
  const responseJson = await response.json();
  return responseJson.message || responseJson.detail || i18n.t(k.UNKNOWN_ERROR);
};
