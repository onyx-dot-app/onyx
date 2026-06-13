"use client";

import { useState } from "react";
import Link from "next/link";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { Button } from "@opal/components";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { logout } from "@/lib/user";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useLicense } from "@/hooks/useLicense";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { ApplicationStatus } from "@/interfaces/settings";
import Text from "@/refresh-components/texts/Text";
import { SvgLock } from "@opal/icons";

const linkClassName = "text-action-link-05 hover:text-action-link-06 underline";

interface ResubscriptionSessionResponse {
  sessionId: string | null;
  url: string | null;
  requires_payment_method_update: boolean;
}

const fetchResubscriptionSession =
  async (): Promise<ResubscriptionSessionResponse> => {
    const response = await fetch("/api/tenants/create-subscription-session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });
    if (!response.ok) {
      throw new Error("创建续订会话失败");
    }
    return response.json();
  };

export default function AccessRestricted() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: license } = useLicense();
  const settings = useSettingsContext();

  const isSeatLimitExceeded =
    settings.settings.application_status ===
    ApplicationStatus.SEAT_LIMIT_EXCEEDED;
  const hadPreviousLicense = license?.has_license === true;
  const showRenewalMessage = NEXT_PUBLIC_CLOUD_ENABLED || hadPreviousLicense;

  function getSeatLimitMessage() {
    const { used_seats, seat_count } = settings.settings;
    const counts =
      used_seats != null && seat_count != null
        ? `（${used_seats} 个用户 / ${seat_count} 个席位）`
        : "";
    return `你的组织已超出许可证席位数${counts}。在减少用户数或升级许可证之前，访问会受到限制。`;
  }

  const initialModalMessage = isSeatLimitExceeded
    ? getSeatLimitMessage()
    : showRenewalMessage
      ? NEXT_PUBLIC_CLOUD_ENABLED
        ? "你的 Glomi AI 访问权限因订阅失效而暂时暂停。"
        : "你的 Glomi AI 访问权限因许可证失效而暂时暂停。"
      : "需要企业许可证才能使用 Glomi AI。你的数据仍受保护，许可证激活后即可继续访问。";

  const handleResubscribe = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // `url` covers both the new-checkout and past_due payment-update responses.
      const { url } = await fetchResubscriptionSession();
      if (!url) {
        throw new Error("未返回重定向 URL");
      }
      window.location.href = url;
    } catch (error) {
      console.error("Error creating resubscription session:", error);
      setError("打开续订页面失败。请稍后重试。");
      setIsLoading(false);
    }
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text headingH2>访问受限</Text>
        <SvgLock className="stroke-status-error-05 w-6 h-6" />
      </div>

      <Text text03>{initialModalMessage}</Text>

      {isSeatLimitExceeded ? (
        <>
          <Text text03>
            如果你是管理员，可以在{" "}
            <Link className={linkClassName} href="/admin/users">
              用户管理
            </Link>{" "}
            页面管理用户，或在{" "}
            <Link className={linkClassName} href="/admin/billing">
              管理员账单
            </Link>{" "}
            页面升级许可证。
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              退出登录
            </Button>
          </div>
        </>
      ) : NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text text03>
            请更新付款信息，以恢复访问并继续使用 Glomi AI 的完整能力。
          </Text>

          <Text text03>
            如果你是管理员，可以点击下方按钮管理订阅。其他用户请联系管理员处理。
          </Text>

          <div className="flex flex-row gap-2">
            <Button disabled={isLoading} onClick={handleResubscribe}>
              {isLoading ? "正在加载..." : "重新订阅"}
            </Button>
            <Button
              prominence="secondary"
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              退出登录
            </Button>
          </div>

          {error && <Text className="text-status-error-05">{error}</Text>}
        </>
      ) : (
        <>
          <Text text03>
            {hadPreviousLicense
              ? "如需恢复访问并继续使用 Glomi AI，请联系系统管理员续订许可证。"
              : "如需开始使用，请联系系统管理员获取企业许可证。"}
          </Text>

          <Text text03>
            如果你是管理员，请前往{" "}
            <Link className={linkClassName} href="/admin/billing">
              管理员账单
            </Link>{" "}
            页面{hadPreviousLicense ? "续订" : "激活"}许可证，通过 Stripe 注册，或联系{" "}
            <a className={linkClassName} href="mailto:support@glomi.ai">
              support@glomi.ai
            </a>{" "}
            获取账单协助。
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              退出登录
            </Button>
          </div>
        </>
      )}

      <Text text03>
        需要帮助？加入我们的{" "}
        <InlineExternalLink
          className={linkClassName}
          href="https://discord.gg/4NA5SbzrWb"
        >
          Discord 社区
        </InlineExternalLink>{" "}
        获取支持。
      </Text>
    </ErrorPageLayout>
  );
}
