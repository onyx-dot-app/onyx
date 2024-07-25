type QueryParams = {
  [key: string]: string | number | boolean | null | undefined;
};

export function buildApiPath(base: string, params?: QueryParams): string {
  let queryString = "";
  if (params) {
    const entries = Object.entries(params)
      .filter(([key, value]) => value !== null && value !== undefined)
      .map(
        ([key, value]) =>
          `${encodeURIComponent(key)}=${encodeURIComponent(value!.toString())}`
      );

    if (entries.length > 0) {
      queryString = `?${entries.join("&")}`;
    }
  }

  return `${base}${queryString}`;
}
