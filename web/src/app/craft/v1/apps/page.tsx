import { redirect } from "@opal/navigation";
import { customizeTabHref } from "@/lib/customize/paths";

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
  const target = customizeTabHref("integrations");
  redirect(suffix ? `${target}?${suffix}` : target);
}
