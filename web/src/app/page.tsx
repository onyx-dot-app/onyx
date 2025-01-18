import { redirect } from "next/navigation";

export default async function Page() {
  console.log("DEFAULT CATCH ALL");
  redirect("/auth/login");
}
