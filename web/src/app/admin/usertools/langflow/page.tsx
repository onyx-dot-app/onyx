import i18n from "@/i18n/init-server";
import k from "../../../../i18n/keys";
import { AdminPageTitle } from "@/components/admin/Title";
import { FiTool } from "react-icons/fi";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";
import { redirect } from "next/navigation";

export default async function Page() {
  const isLangflowEditorEnable =
    process.env.NEXT_PUBLIC_ENABLE_LANGFLOW_EDITOR === "true";
  console.log(
    { isLangflowEditorEnable },
    process.env.NEXT_PUBLIC_ENABLE_LANGFLOW_EDITOR
  );
  if (!isLangflowEditorEnable) {
    return redirect("/chat");
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title={i18n.t(k.LANGFLOW_EDITOR)}
        icon={<FiTool size={32} className="my-auto" />}
      />

      <Text className="mb-8">{i18n.t(k.LANGFLOW_DESCRIPTION)}</Text>

      <Text className="mb-8">
        <a
          className="text-link"
          href="https://docs.langflow.org/"
          target="_blank"
        >
          {i18n.t(k.LANGFLOW_DOCUMENTATION)}
        </a>{" "}
      </Text>

      <a
        href={process.env.REACT_APP_LANGFLOW_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Button className="mx-auto" color="green" type="button">
          {i18n.t(k.OPEN_LANGFLOW_EDITOR)}
        </Button>
      </a>
    </div>
  );
}
