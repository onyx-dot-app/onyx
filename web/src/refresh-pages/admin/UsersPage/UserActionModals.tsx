"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { SvgUserPlus, SvgUserX, SvgXCircle, SvgKey } from "@opal/icons";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import {
  deactivateUser,
  activateUser,
  deleteUser,
  cancelInvite,
  resetPassword,
} from "./svc";

// ---------------------------------------------------------------------------
// Shared helper
// ---------------------------------------------------------------------------

async function runAction(
  action: () => Promise<void>,
  successMessage: string,
  onDone: () => void,
  setIsSubmitting: (v: boolean) => void
) {
  setIsSubmitting(true);
  try {
    await action();
    onDone();
    toast.success(successMessage);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : "发生错误");
  } finally {
    setIsSubmitting(false);
  }
}

// ---------------------------------------------------------------------------
// Cancel Invite Modal
// ---------------------------------------------------------------------------

interface CancelInviteModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function CancelInviteModal({
  email,
  onClose,
  onMutate,
}: CancelInviteModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={(props) => (
        <SvgUserX {...props} className="text-action-danger-05" />
      )}
      title="取消邀请"
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          variant="danger"
          onClick={() =>
            runAction(
              () => cancelInvite(email),
              "邀请已取消",
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          取消邀请
        </Button>
      }
    >
      <Text as="p" text03>
        <Text as="span" text05>
          {email}
        </Text>{" "}
        将无法再通过此邀请加入 Glomi AI。
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Deactivate User Modal
// ---------------------------------------------------------------------------

interface DeactivateUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function DeactivateUserModal({
  email,
  onClose,
  onMutate,
}: DeactivateUserModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={(props) => (
        <SvgUserX {...props} className="text-action-danger-05" />
      )}
      title="停用用户"
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          variant="danger"
          onClick={() =>
            runAction(
              () => deactivateUser(email),
              "用户已停用",
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          停用
        </Button>
      }
    >
      <Text as="p" text03>
        <Text as="span" text05>
          {email}
        </Text>{" "}
        将立即失去 Glomi AI 访问权限。其会话和智能体会保留，许可证席位会释放。
        你可以稍后重新启用此账号。
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Activate User Modal
// ---------------------------------------------------------------------------

interface ActivateUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function ActivateUserModal({
  email,
  onClose,
  onMutate,
}: ActivateUserModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={SvgUserPlus}
      title="启用用户"
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          onClick={() =>
            runAction(
              () => activateUser(email),
              "用户已启用",
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          启用
        </Button>
      }
    >
      <Text as="p" text03>
        <Text as="span" text05>
          {email}
        </Text>{" "}
        将重新获得 Glomi AI 访问权限。
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Delete User Modal
// ---------------------------------------------------------------------------

interface DeleteUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function DeleteUserModal({
  email,
  onClose,
  onMutate,
}: DeleteUserModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={(props) => (
        <SvgUserX {...props} className="text-action-danger-05" />
      )}
      title="删除用户"
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          variant="danger"
          onClick={() =>
            runAction(
              () => deleteUser(email),
              "用户已删除",
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          删除
        </Button>
      }
    >
      <Text as="p" text03>
        <Text as="span" text05>
          {email}
        </Text>{" "}
        将从 Glomi AI 中永久移除。该用户的全部会话历史会被删除，
        此操作无法撤销。
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Reset Password Modal
// ---------------------------------------------------------------------------

interface ResetPasswordModalProps {
  email: string;
  onClose: () => void;
}

export function ResetPasswordModal({
  email,
  onClose,
}: ResetPasswordModalProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [newPassword, setNewPassword] = useState<string | null>(null);

  const handleClose = () => {
    onClose();
    setNewPassword(null);
  };

  return (
    <ConfirmationModalLayout
      icon={SvgKey}
      title={newPassword ? "密码已重置" : "重置密码"}
      onClose={isSubmitting ? undefined : handleClose}
      submit={
        newPassword ? (
          <Button onClick={handleClose}>完成</Button>
        ) : (
          <Button
            disabled={isSubmitting}
            variant="danger"
            onClick={async () => {
              setIsSubmitting(true);
              try {
                const result = await resetPassword(email);
                setNewPassword(result.new_password);
              } catch (err) {
                toast.error(
                  err instanceof Error
                    ? err.message
                    : "重置密码失败"
                );
              } finally {
                setIsSubmitting(false);
              }
            }}
          >
            重置密码
          </Button>
        )
      }
    >
      {newPassword ? (
        <div className="flex flex-col gap-2">
          <Text as="p" text03>
            用户{" "}
            <Text as="span" text05>
              {email}
            </Text>{" "}
            的密码已重置。请复制下方新密码，之后不会再次显示。
          </Text>
          <code className="rounded-xs bg-background-neutral-02 px-3 py-2 text-sm select-all">
            {newPassword}
          </code>
        </div>
      ) : (
        <Text as="p" text03>
          这将为用户{" "}
          <Text as="span" text05>
            {email}
          </Text>
          生成一个新的随机密码。其当前密码会立即失效。
        </Text>
      )}
    </ConfirmationModalLayout>
  );
}
