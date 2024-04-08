import { getSettingsSS } from "@/lib/settings";
import { redirect } from "next/navigation";

export default async function Page() {
  const settings = await getSettingsSS();

  if (!settings) {
    redirect("/search");
  }

  if (settings.default_page === "search") {
    redirect("/search");
  } else {
    redirect("/chat");
  }
}
