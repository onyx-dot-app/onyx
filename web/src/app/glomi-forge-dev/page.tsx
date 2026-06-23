"use client";

import { useState } from "react";

import { Button } from "@opal/components/buttons/button/components";
import { SvgLoader, SvgSparkle } from "@opal/icons";
import { cn } from "@opal/utils";

import { useGlomiForgeSession } from "@/hooks/useGlomiForgeSession";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";

interface CreateSessionResponse {
  session_id: string;
  status: string;
}

const DEFAULT_REQUEST =
  "为一款面向中国创作者的 AI Agent 平台生成中文落地页，突出深度研究、工具调用和可分享作品。";

function statusLabel(status: string | undefined): string {
  if (!status) return "待开始";
  const labels: Record<string, string> = {
    queued: "排队中",
    provisioning: "准备沙箱",
    building: "生成中",
    preview_ready: "预览就绪",
    awaiting_feedback: "等待反馈",
    completed: "已完成",
    failed: "失败",
    terminated: "已终止",
  };
  return labels[status] ?? status;
}

export default function GlomiForgeDevPage() {
  const [request, setRequest] = useState(DEFAULT_REQUEST);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const { session, error: loadError } = useGlomiForgeSession(sessionId);

  async function startSession() {
    const trimmedRequest = request.trim();
    if (!trimmedRequest || isStarting) return;

    setIsStarting(true);
    setStartError(null);
    try {
      const response = await fetch("/api/glomi-forge/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          request: trimmedRequest,
          artifact_type: "landing_page",
        }),
      });
      if (!response.ok) {
        throw new Error(`启动失败: ${response.status}`);
      }
      const payload = (await response.json()) as CreateSessionResponse;
      setSessionId(payload.session_id);
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "启动失败");
    } finally {
      setIsStarting(false);
    }
  }

  const errorMessage =
    startError ??
    (loadError instanceof Error ? loadError.message : null) ??
    (session?.last_error?.message as string | undefined) ??
    null;
  const previewUrl = session?.preview_url ?? null;

  return (
    <main className="min-h-screen bg-background-neutral-00 text-text-01">
      <div className="flex h-screen min-h-[720px] flex-col">
        <header className="flex shrink-0 items-center justify-between gap-4 border-b border-border-01 bg-background-tint-01 px-6 py-4">
          <div className="min-w-0">
            <h1 className="font-headline-heading text-text-01">
              Glomi Forge
            </h1>
            <p className="pt-1 font-secondary-body text-text-03">
              {sessionId ?? "landing_page"}
            </p>
          </div>
          <div
            className={cn(
              "shrink-0 rounded-08 border px-3 py-1.5 font-secondary-action",
              errorMessage
                ? "border-status-error-03 bg-status-error-01 text-status-error-05"
                : "border-border-01 bg-background-neutral-00 text-text-03"
            )}
          >
            {errorMessage ? "异常" : statusLabel(session?.status)}
          </div>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)]">
          <section className="flex min-h-0 flex-col gap-4 border-b border-border-01 bg-background-neutral-01 p-4 lg:border-b-0 lg:border-r">
            <InputTextArea
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              rows={10}
              maxRows={16}
              autoResize
              placeholder="描述你要生成的中文落地页"
            />

            <Button
              variant="default"
              prominence="primary"
              icon={isStarting ? SvgLoader : SvgSparkle}
              disabled={!request.trim() || isStarting}
              onClick={startSession}
              width="full"
            >
              {isStarting ? "启动中" : "生成"}
            </Button>

            <div className="min-h-0 flex-1 overflow-auto rounded-08 border border-border-01 bg-background-neutral-00 p-3">
              <dl className="grid gap-3 font-secondary-body text-text-03">
                <div>
                  <dt className="font-secondary-action text-text-04">状态</dt>
                  <dd className="pt-1 text-text-01">
                    {statusLabel(session?.status)}
                  </dd>
                </div>
                <div>
                  <dt className="font-secondary-action text-text-04">会话</dt>
                  <dd className="break-all pt-1 text-text-01">
                    {sessionId ?? "-"}
                  </dd>
                </div>
                {errorMessage && (
                  <div>
                    <dt className="font-secondary-action text-status-error-05">
                      错误
                    </dt>
                    <dd className="break-words pt-1 text-status-error-05">
                      {errorMessage}
                    </dd>
                  </div>
                )}
              </dl>
            </div>
          </section>

          <section className="min-h-0 bg-background-neutral-00 p-4">
            {previewUrl ? (
              <iframe
                className="h-full min-h-[560px] w-full rounded-08 border border-border-01 bg-background-neutral-00"
                src={previewUrl}
                title="Glomi Forge preview"
              />
            ) : (
              <div className="flex h-full min-h-[560px] items-center justify-center rounded-08 border border-border-01 bg-background-neutral-01 font-main-ui-body text-text-03">
                {sessionId ? "等待预览地址" : "尚未生成"}
              </div>
            )}
          </section>
        </div>
      </div>
    </main>
  );
}
