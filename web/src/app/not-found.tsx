import { redirect } from "@opal/navigation";

export default function NotFound() {
  redirect("/auth/login");
}
