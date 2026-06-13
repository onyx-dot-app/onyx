import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import Text from "@/refresh-components/texts/Text";
import { DOCS_BASE_URL } from "@/lib/constants";
import { SvgAlertCircle } from "@opal/icons";

export default function Error() {
  return (
    <ErrorPageLayout>
      <div className="flex flex-row items-center gap-2">
        <Text as="p" headingH2>
          页面加载遇到问题
        </Text>
        <SvgAlertCircle className="w-6 h-6 stroke-text-04" />
      </div>

      <Text as="p" text03>
        加载 Glomi AI 设置时出现问题，可能是配置异常或初始化尚未完成。
      </Text>

      <Text as="p" text03>
        如果你是管理员，请查看{" "}
        <a
          className="text-action-link-05"
          href={`${DOCS_BASE_URL}?utm_source=app&utm_medium=error_page&utm_campaign=config_error`}
          target="_blank"
          rel="noopener noreferrer"
        >
          配置文档
        </a>{" "}
        确认配置步骤。如果你是普通用户，请联系管理员处理。
      </Text>

      <Text as="p" text03>
        需要帮助？你也可以加入我们的{" "}
        <a
          className="text-action-link-05"
          href="https://discord.gg/4NA5SbzrWb"
          target="_blank"
          rel="noopener noreferrer"
        >
          Discord 社区
        </a>{" "}
        获取支持。
      </Text>
    </ErrorPageLayout>
  );
}
