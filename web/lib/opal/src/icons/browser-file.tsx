import type { IconProps } from "@opal/types";

const SvgBrowserFile = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M14 6.66671V3.33337C14 2.59699 13.403 2.00004 12.6667 2.00004H3.33334C2.59696 2.00004 2.00001 2.59699 2.00001 3.33337V12.6667C2.00001 13.4031 2.59696 14 3.33334 14H6.66668M2.00001 5.33337H14"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M12 8.66671H10C9.63182 8.66671 9.33334 8.96518 9.33334 9.33337V14C9.33334 14.3682 9.63182 14.6667 10 14.6667H13.3333C13.7015 14.6667 14 14.3682 14 14V10.6667M12 8.66671L14 10.6667M12 8.66671V10.6667H14"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBrowserFile;
