export class FetchError extends Error {
  status: number;
  info: any;

  constructor(message: string, status: number, info: any) {
    super(message);
    this.status = status;
    this.info = info;
  }
}

const DEFAULT_ERROR_MSG = "An error occurred while fetching the data.";

export const errorHandlingFetcher = async (url: string) => {
  const res = await fetch(url);
  if (!res.ok) {
    const error = new FetchError(
      DEFAULT_ERROR_MSG,
      res.status,
      await res.json()
    );
    throw error;
  }
  return res.json();
};
