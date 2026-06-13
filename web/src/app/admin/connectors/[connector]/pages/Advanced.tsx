import React from "react";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/Field";
import { Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
interface AdvancedFormPageProps {
  defaultPruneFreqHours?: number;
}

export default function AdvancedFormPage({
  defaultPruneFreqHours = 600,
}: AdvancedFormPageProps) {
  return (
    <div className="py-4 flex flex-col gap-y-6 rounded-lg max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-text-800">
        高级配置
      </h2>

      <NumberInput
        description={`
          对照来源检查所有文档，并删除已不存在的文档。
          注意：此过程会检查每个文档，因此提高频率时请谨慎。
          默认值为 ${defaultPruneFreqHours} 小时（${Math.round(
            defaultPruneFreqHours / 24
          )} 天）。支持小数小时（例如 0.1 小时 = 6 分钟）。
          输入 0 可禁用此连接器的修剪。
        `}
        label="修剪频率（小时）"
        name="pruneFreq"
      />

      <NumberInput
        description="从来源拉取新文档的频率（分钟）。如果输入 0，则不会为此连接器拉取新文档。"
        label="刷新频率（分钟）"
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext="早于此日期的文档不会被拉取"
        optional
        label="索引开始日期"
        name="indexingStart"
      />
      <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
        <Button variant="danger" icon={SvgTrash} type="submit">
          重置
        </Button>
      </div>
    </div>
  );
}
