// The app's and the admin panel's chromes. Import them from here.
// AdminSSChrome is a server component: a client component cannot import this
// barrel without pulling it in, so import those from here only on the server.
export {
  default as AppChrome,
  type AppChromeProps,
} from "@/layouts/chromes/AppChrome";
export { AppChromeLoader } from "@/layouts/chromes/AppChromeLoader";
export {
  default as AdminChrome,
  type AdminChromeProps,
} from "@/layouts/chromes/AdminChrome";
export {
  default as AdminSSChrome,
  type AdminSSChromeProps,
} from "@/layouts/chromes/AdminSSChrome";
