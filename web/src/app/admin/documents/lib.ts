export const updateBoost = async (documentId: string, boost: number) => {
  const response = await fetch("/api/manage/admin/doc-boosts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      document_id: documentId,
      boost,
    }),
  });
  if (response.ok) {
    return null;
  }
  const responseJson = await response.json();
  return responseJson.message || responseJson.detail || "Unknown error";
};

export const updateHiddenStatus = async (
  documentId: string,
  isHidden: boolean
) => {
  const response = await fetch("/api/manage/admin/doc-hidden", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      document_id: documentId,
      hidden: isHidden,
    }),
  });
  return response;
};
