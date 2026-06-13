"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { mutate as globalMutate } from "swr";
import { SettingsLayouts } from "@opal/layouts";
import { Button, Card, Text } from "@opal/components";
import { SvgPlug } from "@opal/icons";
import { CRAFT_APPS_PATH } from "@/app/craft/v1/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { completeExternalAppOAuthCallback } from "@/app/craft/services/externalAppsService";

type Status = "exchanging" | "success" | "error";

export default function ExternalAppsOAuthCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const code = params?.get("code") ?? null;
  const state = params?.get("state") ?? null;
  const slackError = params?.get("error") ?? null;

  const [status, setStatus] = useState<Status>("exchanging");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  // OAuth `code` is single-use — gate against React Strict Mode and
  // remount-induced double exchanges, which would 400 on the second.
  const hasExchanged = useRef(false);

  useEffect(() => {
    if (slackError) {
      setStatus("error");
      setErrorMessage(`OAuth 已取消或被拒绝：${slackError}`);
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setErrorMessage("回调 URL 中缺少 code 或 state。");
      return;
    }
    if (hasExchanged.current) return;
    hasExchanged.current = true;

    async function exchange() {
      try {
        await completeExternalAppOAuthCallback(code!, state!);
        setStatus("success");
        await globalMutate(SWR_KEYS.buildExternalApps);
        setTimeout(() => router.push(CRAFT_APPS_PATH as Route), 800);
      } catch (e) {
        setStatus("error");
        setErrorMessage(e instanceof Error ? e.message : String(e));
      }
    }

    exchange();
  }, [code, state, slackError, router]);

  return (
    <SettingsLayouts.Root width="sm">
      <SettingsLayouts.Header
        icon={SvgPlug}
        title="正在连接应用"
        description="正在完成 OAuth 握手..."
      />
      <SettingsLayouts.Body>
        <Card background="light" border="solid" rounding="lg">
          <div className="flex flex-col gap-2">
            {status === "exchanging" && (
              <Text font="main-content-body">
                正在交换授权码...
              </Text>
            )}
            {status === "success" && (
              <Text font="main-content-body">
                已连接。正在返回你的应用...
              </Text>
            )}
            {status === "error" && (
              <>
                <Text font="main-content-body">连接失败。</Text>
                {errorMessage && (
                  <Text font="secondary-body" color="text-03">
                    {errorMessage}
                  </Text>
                )}
                <div className="pt-2">
                  <Button onClick={() => router.push(CRAFT_APPS_PATH as Route)}>
                    返回我的应用
                  </Button>
                </div>
              </>
            )}
          </div>
        </Card>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
