import { redirect } from "next/navigation";

export default async function Page() {
  redirect("/admin/indexing/status?new_organization=true");
}
