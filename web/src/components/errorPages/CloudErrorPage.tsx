import Text from "@/refresh-components/texts/Text";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";

export default function CloudError() {
  return (
    <ErrorPageLayout>
      <Text as="p" headingH2>
        系统维护中
      </Text>

      <Text as="p" text03>
        Glomi AI 正在进行维护，请几分钟后再回来查看。
      </Text>

      <Text as="p" text03>
        给你带来不便我们很抱歉，感谢你的耐心等待。
      </Text>
    </ErrorPageLayout>
  );
}
