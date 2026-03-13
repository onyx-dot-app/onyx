import type { IconProps } from "@opal/types";

const SvgFilterPlus = ({ size, ...props }: IconProps) => (
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
      d="M9.5 12.5L6.83334 11.1667V7.80667L1.5 1.5H14.8333L12.1667 4.65333M12.1667 7V9.5M12.1667 9.5V12M12.1667 9.5H9.66667M12.1667 9.5H14.6667"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFilterPlus;
