import { SvgUser } from "@opal/icons";
import { DEFAULT_AVATAR_SIZE_PX } from "@/lib/constants";
import { getUserInitials } from "@/lib/user";
import Text from "@/refresh-components/texts/Text";
import type { User } from "@/lib/types";

export interface UserAvatarProps {
  user: User;
  size?: number;
}

export default function UserAvatar({
  user,
  size = DEFAULT_AVATAR_SIZE_PX,
}: UserAvatarProps) {
  const initials = getUserInitials(
    user.personalization?.name ?? null,
    user.email
  );

  if (!initials) {
    return (
      <div
        role="img"
        aria-label={`${user.email} avatar`}
        className="flex items-center justify-center rounded-full bg-background-tint-01"
        style={{ width: size, height: size }}
      >
        <SvgUser size={size * 0.55} className="stroke-text-03" aria-hidden />
      </div>
    );
  }

  return (
    <div
      role="img"
      aria-label={`${user.email} avatar`}
      className="flex items-center justify-center rounded-full bg-background-neutral-inverted-00"
      style={{ width: size, height: size }}
    >
      <Text
        inverted
        secondaryAction
        text05
        className="select-none"
        style={{ fontSize: size * 0.4 }}
      >
        {initials}
      </Text>
    </div>
  );
}
