export const deleteSearchSettings = async (search_settings_id: number) => {
  const response = await fetch(`/api/search-settings/delete-search-settings`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ search_settings_id }),
  });
  return response;
};
