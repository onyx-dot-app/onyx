"use client";

import { useState } from "react";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { toast } from "@/hooks/useToast";
import { SvgArrowRight, SvgUsers, SvgX } from "@opal/icons";
import { logout } from "@/lib/user";
import { useUser } from "@/providers/UserProvider";
import { NewTenantInfo } from "@/lib/types";
import { useRouter } from "next/navigation";
import Text from "@/refresh-components/texts/Text";
import { InputErrorText } from "@opal/layouts";

// App domain should not be hardcoded
const APP_DOMAIN = process.env.NEXT_PUBLIC_APP_DOMAIN || "glomi.ai";

export interface NewTenantModalProps {
  tenantInfo: NewTenantInfo;
  isInvite?: boolean;
  onClose?: () => void;
}

export default function NewTenantModal({
  tenantInfo,
  isInvite = false,
  onClose,
}: NewTenantModalProps) {
  const router = useRouter();
  const { user } = useUser();
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleJoinTenant() {
    setIsLoading(true);
    setError(null);

    try {
      if (isInvite) {
        // Accept the invitation through the API
        const response = await fetch("/api/tenants/users/invite/accept", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ tenant_id: tenantInfo.tenant_id }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(
            errorData.detail ||
              errorData.message ||
              "接受邀请失败"
          );
        }

        toast.success("你已接受邀请。");
      } else {
        // For non-invite flow, just show success message
        toast.success("正在处理你的团队加入请求...");
      }

      // Common logout and redirect for both flows
      await logout();
      router.push(`/auth/join?email=${encodeURIComponent(user?.email || "")}`);
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "加入团队失败，请重试。";

      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  async function handleRejectInvite() {
    if (!isInvite) return;

    setIsLoading(true);
    setError(null);

    try {
      // Deny the invitation through the API
      const response = await fetch("/api/tenants/users/invite/deny", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ tenant_id: tenantInfo.tenant_id }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(
          errorData.detail ||
            errorData.message ||
            "拒绝邀请失败"
        );
      }

      toast.info("你已拒绝邀请。");
      onClose?.();
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "拒绝邀请失败，请重试。";

      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  }

  const title = isInvite
    ? `你受邀加入 ${APP_DOMAIN} 上已有 ${
        tenantInfo.number_of_users
      } 位成员的团队。`
    : `你加入 ${APP_DOMAIN} 上 ${tenantInfo.number_of_users} 位成员团队的请求已获批准。`;

  const description = isInvite
    ? `接受邀请后，你将加入现有 ${APP_DOMAIN} 团队，并失去当前团队的访问权限。注意：你也会失去当前智能体、提示词、聊天和已连接数据源的访问权限。`
    : `要完成加入团队，请使用 ${user?.email} 重新认证。`;

  return (
    <Modal open>
      <Modal.Content width="sm" height="sm" preventAccidentalClose={false}>
        <Modal.Header icon={SvgUsers} title={title} onClose={onClose} />

        <Modal.Body>
          <Text>{description}</Text>
          {error && <InputErrorText>{error}</InputErrorText>}
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              isInvite ? (
                <Button
                  disabled={isLoading}
                  prominence="secondary"
                  onClick={handleRejectInvite}
                  icon={SvgX}
                >
                  拒绝
                </Button>
              ) : undefined
            }
            submit={
              <Button
                disabled={isLoading}
                onClick={handleJoinTenant}
                rightIcon={SvgArrowRight}
              >
                {isLoading
                  ? isInvite
                    ? "正在接受..."
                    : "正在加入..."
                  : isInvite
                    ? "接受邀请"
                    : "重新认证"}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
