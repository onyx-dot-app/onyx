// NOTE: Supports cases where `content-type` is other than `json`
const getBody = <T>(c: Response | Request): Promise<T> => {
  const contentType = c.headers.get("content-type");

  if (contentType && contentType.includes("application/json")) {
    return c.json();
  }

  if (contentType && contentType.includes("application/pdf")) {
    return c.blob() as Promise<T>;
  }

  return c.text() as Promise<T>;
};

// NOTE(rkuo): we must return a relative URL to get the routes working
const getUrl = (contextUrl: string): string => {
  const url = new URL(contextUrl);
  const pathname = url.pathname;
  const search = url.search;
  const baseUrl = "/api";

  const requestUrl = `${baseUrl}${pathname}${search}`;
  return requestUrl.toString();
};

// NOTE: Add headers
const getHeaders = (headers?: HeadersInit): HeadersInit => {
  return {
    ...headers,
  };
};

export const orvalFetch = async <T>(
  url: string,
  options: RequestInit
): Promise<T> => {
  const isServer = typeof window === "undefined";
  const requestUrl = getUrl(url);
  const requestHeaders = getHeaders(options.headers);

  let requestInit: RequestInit;

  if (isServer) {
    // Server-side: manually attach cookies
    const { cookies } = require("next/headers");
    // const cookieString = cookies().toString();
    // console.log('Server-side cookies:', cookieString);

    requestInit = {
      ...options,
      headers: {
        ...requestHeaders,
        Cookie: cookies().toString(), // Manually attach cookies on server
      },
    };
  } else {
    // Client-side: let browser handle cookies
    // console.log('Client-side cookies available:', document.cookie ? 'Yes' : 'No');

    requestInit = {
      ...options,
      headers: requestHeaders,
      credentials: "include", // Browser will automatically include cookies
    };
  }

  // console.log('Request URL:', requestUrl);
  // console.log('Request headers:', requestInit.headers);

  const response = await fetch(requestUrl, requestInit);
  const data = await getBody<T>(response);

  return { status: response.status, data, headers: response.headers } as T;
};
