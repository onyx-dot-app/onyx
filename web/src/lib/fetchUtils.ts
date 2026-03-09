export const getErrorMsg = async (response: Response) => {
  if (response.ok) {
    return null;
  }
  const responseJson = await response.json();
  return responseJson.detail || responseJson.message || "Unknown error";
};
