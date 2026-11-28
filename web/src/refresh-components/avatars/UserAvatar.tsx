import { IconContainer } from "@opal/components";
import { DEFAULT_AVATAR_SIZE_PX } from "@/lib/constants";
import { getUserInitials } from "@/lib/users/svc";

export interface UserAvatarProps {
  /** Initials come from this name, else from the email. */
  name: string | null;
  email: string;
  /** Profile photo. The initials show when it is missing or fails to load. */
  imageUrl?: string | null;
  size?: number;
}

export default function UserAvatar({
  name,
  email,
  imageUrl,
  size = DEFAULT_AVATAR_SIZE_PX,
}: UserAvatarProps) {
  return (
    <div role="img" aria-label={`${email} avatar`}>
      <IconContainer
        avatar="user"
        initials={getUserInitials(name, email)}
        src={imageUrl}
        diameter={size}
      />
    </div>
  );
}
