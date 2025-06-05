import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import { ActionsTable } from "./ActionTable";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { FiPlusSquare } from "react-icons/fi";
import Link from "next/link";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CreateButton from "@/components/ui/createButton";

export default async function Page() {
  const toolResponse = await fetchSS("/tool");

  if (!toolResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Что-то пошло не так :("
        errorMsg={`${i18n.t(
          k.FAILED_TO_FETCH_TOOLS
        )} ${await toolResponse.text()}`}
      />
    );
  }

  const tools = (await toolResponse.json()) as ToolSnapshot[];

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ToolIcon size={32} className="my-auto" />}
        title="Инструменты"
      />

      <Text className="mb-2">{i18n.t(k.ACTIONS_ALLOW_ASSISTANTS_TO_RE)}</Text>

      <div>
        <Separator />

        <Title>{i18n.t(k.CREATE_AN_ACTION)}</Title>
        <CreateButton href="/admin/actions/new" text="Новый инструмент" />

        <Separator />

        <Title>{i18n.t(k.EXISTING_ACTIONS)}</Title>
        <ActionsTable tools={tools} />
      </div>
    </div>
  );
}
