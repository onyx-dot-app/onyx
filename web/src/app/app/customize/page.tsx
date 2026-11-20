import { redirect } from "@opal/navigation";
import { customizeTabHref } from "@/lib/customize/paths";

export default function Page() {
  redirect(customizeTabHref("skills"));
}
