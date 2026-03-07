import BackButton from "@/refresh-components/buttons/BackButton";
import { NewSlackBotForm } from "../SlackBotCreationForm";

export default async function NewSlackBotPage() {
  return (
    <>
      <BackButton routerOverride="/admin/bots" />

      <NewSlackBotForm />
    </>
  );
}
