import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import { PersonasTable } from "./PersonaTable";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Separator } from "@/components/ui/separator";
import { AssistantsIcon } from "@/components/icons/icons";
import { AdminPageTitle } from "@/components/admin/Title";
import { SubLabel } from "@/components/admin/connectors/Field";
import CreateButton from "@/components/ui/createButton";
export default async function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<AssistantsIcon size={32} />} title="Ассистенты" />

      <Text className="mb-2">{i18n.t(k.ASSISTANTS_ARE_A_WAY_TO_BUILD)}</Text>
      <Text className="mt-2">{i18n.t(k.THEY_ALLOW_YOU_TO_CUSTOMIZE)}</Text>
      <div className="text-sm">
        <ul className="list-disc mt-2 ml-4">
          <li>{i18n.t(k.THE_PROMPT_USED_BY_YOUR_LLM_OF)}</li>
          <li>{i18n.t(k.THE_DOCUMENTS_THAT_ARE_USED_AS)}</li>
        </ul>
      </div>

      <div>
        <Separator />

        <Title>{i18n.t(k.CREATE_AN_ASSISTANT)}</Title>
        <CreateButton
          href="/assistants/new?admin=true"
          text="Новый ассистент"
        />

        <Separator />

        <Title>{i18n.t(k.EXISTING_ASSISTANTS)}</Title>
        <SubLabel>{i18n.t(k.ASSISTANTS_WILL_BE_DISPLAYED_A)}</SubLabel>
        <PersonasTable />
      </div>
    </div>
  );
}
