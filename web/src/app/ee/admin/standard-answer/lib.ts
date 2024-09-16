export interface StandardAnswerCategoryCreationRequest {
  name: string;
}

export interface StandardAnswerCreationRequest {
  keyword: string;
  answer: string;
  categories: number[];
  matchRegex: boolean;
  matchAnyKeywords: boolean;
}

const buildRequestBodyFromStandardAnswerCategoryCreationRequest = (
  request: StandardAnswerCategoryCreationRequest
) => {
  return JSON.stringify({
    name: request.name,
  });
};

export const createStandardAnswerCategory = async (
  request: StandardAnswerCategoryCreationRequest
) => {
  return fetch("/api/manage/admin/standard-answer/category", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromStandardAnswerCategoryCreationRequest(request),
  });
};

export const updateStandardAnswerCategory = async (
  id: number,
  request: StandardAnswerCategoryCreationRequest
) => {
  return fetch(`/api/manage/admin/standard-answer/category/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromStandardAnswerCategoryCreationRequest(request),
  });
};

const buildRequestBodyFromStandardAnswerCreationRequest = (
  request: StandardAnswerCreationRequest
) => {
  return JSON.stringify({
    keyword: request.keyword,
    answer: request.answer,
    categories: request.categories,
    match_regex: request.matchRegex,
    match_any_keywords: request.matchAnyKeywords,
  });
};

export const createStandardAnswer = async (
  request: StandardAnswerCreationRequest
) => {
  return fetch("/api/manage/admin/standard-answer", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromStandardAnswerCreationRequest(request),
  });
};

export const updateStandardAnswer = async (
  id: number,
  request: StandardAnswerCreationRequest
) => {
  return fetch(`/api/manage/admin/standard-answer/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: buildRequestBodyFromStandardAnswerCreationRequest(request),
  });
};

export const deleteStandardAnswer = async (id: number) => {
  return fetch(`/api/manage/admin/standard-answer/${id}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
};
