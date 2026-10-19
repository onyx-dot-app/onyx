import { redirect } from "next/navigation";
import { CRAFT_PLUGINS_PATH } from "@/app/craft/v1/constants";

interface PageProps {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function Page({ searchParams }: PageProps) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(await searchParams)) {
    if (Array.isArray(value)) value.forEach((item) => query.append(key, item));
    else if (value !== undefined) query.set(key, value);
  }
  const suffix = query.toString();
  redirect(suffix ? `${CRAFT_PLUGINS_PATH}?${suffix}` : CRAFT_PLUGINS_PATH);
}
