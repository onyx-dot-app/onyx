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
        title="Редактор Langflow"
        icon={<FiTool size={32} className="my-auto" />}
      />

      <Text className="mb-8">
        Langflow — это инструмент с открытым исходным кодом для создания и
        управления чат-ботами, использующими большие языковые модели (LLM),
        такие как GPT и другие. Langflow предназначен для упрощения разработки
        приложений на основе ИИ с минимальным количеством кода или вовсе без
        него. Инструмент предоставляет визуальный интерфейс, который позволяет
        пользователям конструировать сложные цепочки взаимодействий между
        моделью и пользователем через блоки, похожие на блоки в конструкторе.
      </Text>

      <Text className="mb-8">
        <a
          className="text-link"
          href="https://docs.langflow.org/"
          target="_blank"
        >
          Документация Langflow
        </a>{" "}
      </Text>

      <a
        href={process.env.REACT_APP_LANFLOW_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Button className="mx-auto" color="green" type="button">
          {"Открыть редактор Langflow"}
        </Button>
      </a>
    </div>
  );
}
