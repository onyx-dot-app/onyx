// Next's own URL reads and server helpers, unchanged. They live here so that
// nothing outside @opal/navigation imports `next/navigation`.
export {
  usePathname,
  useSearchParams,
  useParams,
  useSelectedLayoutSegment,
  useSelectedLayoutSegments,
  redirect,
  permanentRedirect,
  notFound,
  RedirectType,
  type ReadonlyURLSearchParams,
} from "next/navigation";
