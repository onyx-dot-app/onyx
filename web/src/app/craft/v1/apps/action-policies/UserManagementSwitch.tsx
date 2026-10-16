"use client";
import { InputSwitch, Text } from "@opal/components";
import { useTranslations } from "next-intl";
interface UserManagementSwitchProps {
  value: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}
export default function UserManagementSwitch({
  value,
  onChange,
  disabled = false,
}: UserManagementSwitchProps) {
  const t = useTranslations("craft.actionPolicies");
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex flex-col">
        <Text font="main-ui-action">{t("userManagement")}</Text>
        <Text font="secondary-body" color="text-03">
          {t("userManagementDescription")}
        </Text>
      </div>
      <InputSwitch
        disabled={disabled}
        checked={value}
        onCheckedChange={onChange}
        aria-label={t("userManagement")}
      />
    </div>
  );
}
