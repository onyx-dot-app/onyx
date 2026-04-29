import type { IconProps } from "@opal/types";

const MAX_NOTIFICATIONS = 9;

interface NotificationBubbleProps extends IconProps {
  /** Optional count to display inside the bubble. */
  count?: number;
}

const SvgNotificationBubble = ({
  size,
  count,
  ...props
}: NotificationBubbleProps) => {
  // When no count is provided, render a simple dot
  if (count === undefined) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 6 6"
        fill="none"
        xmlns="http://www.w3.org/2000/svg"
        {...props}
      >
        <circle cx={3} cy={3} r={3} fill="var(--action-link-05)" />
      </svg>
    );
  }

  // With a count, render a badge with the number inside
  const displayCount =
    count > MAX_NOTIFICATIONS ? `${MAX_NOTIFICATIONS}+` : String(count);

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ minWidth: size, minHeight: size }}
    >
      <div
        className="flex items-center justify-center rounded-full px-1"
        style={{
          backgroundColor: "var(--action-link-05)",
          minWidth: 16,
          height: 16,
        }}
      >
        <span
          className="text-text-light-05 font-medium leading-none"
          style={{ fontSize: 10 }}
        >
          {displayCount}
        </span>
      </div>
    </div>
  );
};

export default SvgNotificationBubble;
