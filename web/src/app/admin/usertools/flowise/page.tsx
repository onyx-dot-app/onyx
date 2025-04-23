import { AdminPageTitle } from "@/components/admin/Title";
import { FiTool } from "react-icons/fi";
import { fetchSS } from "@/lib/utilsSS";
import Text from "@/components/ui/text";
import { Button } from "@/components/ui/button";

import RedirectBackOnCondition from "@/components/RedirectBackOnCondition";

export default async function Page() {
  const isFlowiseEditorEnable =
    process.env.NEXT_PUBLIC_ENABLE_FLOWISE_EDITOR === "true";
  console.log(
    { isFlowiseEditorEnable },
    process.env.NEXT_PUBLIC_ENABLE_FLOWISE_EDITOR
  );
  if (!isFlowiseEditorEnable) {
    return <RedirectBackOnCondition condition={!isFlowiseEditorEnable} />;
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Редактор Flowise"
        icon={<FiTool size={32} className="my-auto" />}
      />

      <Text className="mb-8">
        Flowise — это инструмент с открытым исходным кодом для создания и
        управления чат-ботами, использующими большие языковые модели (LLM),
        такие как GPT и другие. Flowise предназначен для упрощения разработки
        приложений на основе ИИ с минимальным количеством кода или вовсе без
        него. Инструмент предоставляет визуальный интерфейс, который позволяет
        пользователям конструировать сложные цепочки взаимодействий между
        моделью и пользователем через блоки, похожие на блоки в конструкторе.
      </Text>

      <Text className="mb-8">
        <a
          className="text-link"
          href="https://docs.flowiseai.com/"
          target="_blank"
        >
          Документация Flowise
        </a>{" "}
      </Text>

      <a
        href={process.env.REACT_APP_FLOWISE_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Button className="mx-auto" color="green" size="md" type="button">
          {"Открыть редактор Flowise"}
        </Button>
      </a>
    </div>
  );
}
