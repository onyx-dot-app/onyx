export interface DocumentSetCreationRequest {
  name: string;
  description: string;
  cc_pair_ids: number[];
  is_public: boolean;
  users: string[];
  groups: number[];
}

export const createDocumentSet = async ({
  name,
  description,
  cc_pair_ids,
  is_public,
  users,
  groups,
}: DocumentSetCreationRequest) => {
  return fetch("/api/manage/admin/document-set", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name,
      description,
      cc_pair_ids,
      is_public,
      users,
      groups,
    }),
  });
};

interface DocumentSetUpdateRequest {
  id: number;
  description: string;
  cc_pair_ids: number[];
  is_public: boolean;
  users: string[];
  groups: number[];
}

export const updateDocumentSet = async ({
  id,
  description,
  cc_pair_ids,
  is_public,
  users,
  groups,
}: DocumentSetUpdateRequest) => {
  return fetch("/api/manage/admin/document-set", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      id,
      description,
      cc_pair_ids,
      is_public,
      users,
      groups,
    }),
  });
};

export const deleteDocumentSet = async (id: number) => {
  return fetch(`/api/manage/admin/document-set/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};
