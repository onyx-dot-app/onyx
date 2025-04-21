import { AdminPageTitle } from "@/components/admin/Title";
import { FiTool } from "react-icons/fi";
import { fetchSS } from "@/lib/utilsSS";
import { Callout, Text } from "@tremor/react";
import { Button } from "@tremor/react";

import RedirectBackOnCondition from "@/components/RedirectBackOnCondition";

export default async function Page() {
  const isLangfuseEditorEnable =
    process.env.NEXT_PUBLIC_ENABLE_LANGFUSE_EDITOR === "true";
  console.log(
    { isLangfuseEditorEnable },
    process.env.NEXT_PUBLIC_ENABLE_LANGFUSE_EDITOR
  );
  if (!isLangfuseEditorEnable) {
    return <RedirectBackOnCondition condition={!isLangfuseEditorEnable} />;
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Мониторинг Langfuse"
        icon={<FiTool size={32} className="my-auto" />}
      />

      <Text className="mb-8">
        Langfuse - это платформа инженерии LLM с открытым исходным кодом,
        которая предоставляет функции наблюдаемости, аналитики, оценок,
        управления промптами и экспериментов, чтобы помочь администраторам
        отлаживать, анализировать и улучшать работу цифровых помощников.
      </Text>

      <Text className="mb-8">
        <a
          className="text-link"
          href="https://langfuse.com/docs"
          target="_blank"
        >
          Документация Langfuse
        </a>{" "}
      </Text>

      <a
        href={process.env.REACT_APP_LANGFUSE_URL}
        target="_blank"
        rel="noopener noreferrer"
      >
        <Button className="mx-auto" color="green" size="md" type="button">
          {"Открыть Langfuse"}
        </Button>
      </a>
    </div>
  );
}
