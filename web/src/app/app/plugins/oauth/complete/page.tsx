"use client";

import { useTranslations } from "next-intl";
import { Button, Card } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgConnected } from "@opal/illustrations";
import { useNavigation } from "@opal/navigation";

/** The page a sign-in returns to when it started with no other page. */
export default function MemberPluginOAuthCompletePage() {
  const t = useTranslations("plugins.member.oauthComplete");
  const navigation = useNavigation();
  return (
    <Section justifyContent="center" padding={6}>
      <Section width={24} height="auto">
        <Card
          padding={6}
          rounding={4}
          color="background-tint-00"
          border="solid"
        >
          <Section alignItems="stretch" gap={4} height="auto">
            <IllustrationContent
              illustration={SvgConnected}
              title={t("title")}
              description={t("description")}
            />
            <Button {...navigation.linkTo("/app/plugins")} width="full">
              {t("back")}
            </Button>
            <Button prominence="tertiary" onClick={() => window.close()}>
              {t("close")}
            </Button>
          </Section>
        </Card>
      </Section>
    </Section>
  );
}
