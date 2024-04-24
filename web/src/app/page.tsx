import { fetchSettingsSS } from "@/components/settings/lib";
import { redirect } from "next/navigation";

export default async function Page() {
  const settings = await fetchSettingsSS();

  if (!settings) {
    redirect("/search");
  }

  if (settings.settings.default_page === "search") {
    redirect("/search");
  } else {
    redirect("/chat");
  }
}
