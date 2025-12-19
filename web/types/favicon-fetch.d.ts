declare module "favicon-fetch" {
  type FetchFaviconArg = string | { uri: string };
  const fetchFavicon: (input: FetchFaviconArg) => Promise<string | undefined>;
  export default fetchFavicon;
}
