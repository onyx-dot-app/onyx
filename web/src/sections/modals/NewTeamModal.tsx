"use client";

import { useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { Dialog } from "@headlessui/react";
import { Button } from "@opal/components";
import { toast } from "@/hooks/useToast";
import { useUser } from "@/providers/UserProvider";
import { useModalContext } from "@/components/context/ModalContext";
import {
  SvgArrowRight,
  SvgArrowUp,
  SvgCheckCircle,
  SvgOrganization,
  SvgPlus,
  SvgSimpleLoader,
} from "@opal/icons";
export interface TenantByDomainResponse {
  tenant_id: string;
  number_of_users: number;
  creator_email: string;
}

export default function NewTeamModal() {
  const { showNewTeamModal, setShowNewTeamModal } = useModalContext();
  const [existingTenant, setExistingTenant] =
    useState<TenantByDomainResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [hasRequestedInvite, setHasRequestedInvite] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { user } = useUser();
  const appDomain = user?.email.split("@")[1];
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const hasNewTeamParam = searchParams?.has("new_team");
    if (hasNewTeamParam) {
      setShowNewTeamModal(true);
      fetchTenantInfo();

      // Remove the new_team parameter from the URL without page reload
      const newParams = new URLSearchParams(searchParams?.toString() || "");
      newParams.delete("new_team");
      const newUrl =
        window.location.pathname +
        (newParams.toString() ? `?${newParams.toString()}` : "");
      window.history.replaceState({}, "", newUrl);
    }
  }, [searchParams, setShowNewTeamModal]);

  const fetchTenantInfo = async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/existing-team-by-domain");
      if (!response.ok) {
        throw new Error(`获取团队信息失败：${response.status}`);
      }
      const responseJson = await response.json();
      if (!responseJson) {
        setShowNewTeamModal(false);
        setExistingTenant(null);
        return;
      }

      const data = responseJson as TenantByDomainResponse;
      setExistingTenant(data);
    } catch (error) {
      console.error("Failed to fetch tenant info:", error);
      setError("无法获取团队信息。请稍后重试。");
    } finally {
      setIsLoading(false);
    }
  };

  const handleRequestInvite = async () => {
    if (!existingTenant) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const response = await fetch("/api/tenants/users/invite/request", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tenant_id: existingTenant.tenant_id }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          errorData.detail || errorData.message || "请求邀请失败"
        );
      }

      setHasRequestedInvite(true);
      toast.success("你的邀请请求已发送给团队管理员。");
    } catch (error) {
      const message =
        error instanceof Error ? error.message : "请求邀请失败";
      setError(message);
      toast.error(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleContinueToNewOrg = () => {
    const newUrl = window.location.pathname;
    router.replace(newUrl as Route);
    setShowNewTeamModal(false);
  };

  // Update the close handler to use the context
  const handleClose = () => {
    setShowNewTeamModal(false);
  };

  // Only render if showNewTeamModal is true
  if (!showNewTeamModal || isLoading) return null;

  return (
    <Dialog
      open={showNewTeamModal}
      onClose={handleClose}
      className="relative z-1000"
    >
      {/* Modal backdrop */}
      <div className="fixed inset-0 bg-mask-03" aria-hidden="true" />

      <div className="fixed inset-0 flex items-center justify-center p-4">
        <Dialog.Panel className="mx-auto w-full max-w-md rounded-lg bg-background-neutral-00 p-6 shadow-xl border">
          <Dialog.Title className="text-xl font-semibold mb-4 flex items-center">
            {hasRequestedInvite ? (
              <>
                <SvgCheckCircle className="mr-2 h-5 w-5 stroke-text-05" />
                加入请求已发送
              </>
            ) : (
              <>
                <SvgOrganization className="mr-2 h-5 w-5 stroke-text-04" />
                我们找到了 {appDomain} 的现有团队
              </>
            )}
          </Dialog.Title>

          {isLoading ? (
            <div className="py-8 text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-border-05 mx-auto mb-4"></div>
              <p>正在加载团队信息...</p>
            </div>
          ) : error ? (
            <div className="space-y-4">
              <p className="text-status-text-error-05">{error}</p>
              <div className="flex w-full pt-2">
                <Button
                  onClick={handleContinueToNewOrg}
                  width="full"
                  rightIcon={SvgArrowRight}
                >
                  继续使用新团队
                </Button>
              </div>
            </div>
          ) : hasRequestedInvite ? (
            <div className="space-y-4">
              <p className="text-text-04">
                你的加入请求已发送。在等待 {appDomain} 的管理员批准时，你可以先以自己的团队继续探索。
              </p>
              <div className="flex w-full pt-2">
                <Button
                  onClick={handleContinueToNewOrg}
                  width="full"
                  rightIcon={SvgArrowRight}
                >
                  等待期间试用 Glomi AI
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-4">
              <p className="text-text-03 text-sm mb-2">
                {appDomain} 的任一管理员都可以批准你的加入请求。
              </p>
              <div className="flex flex-col items-center justify-center gap-4 mt-4">
                <Button
                  disabled={isSubmitting}
                  onClick={handleRequestInvite}
                  width="full"
                  icon={isSubmitting ? SvgSimpleLoader : SvgArrowUp}
                >
                  {isSubmitting
                    ? "正在发送请求..."
                    : "请求加入你的团队"}
                </Button>
              </div>
              <Button
                onClick={handleContinueToNewOrg}
                width="full"
                icon={SvgPlus}
                prominence="secondary"
              >
                继续使用新团队
              </Button>
            </div>
          )}
        </Dialog.Panel>
      </div>
    </Dialog>
  );
}
