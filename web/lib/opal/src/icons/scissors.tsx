import type { IconProps } from "@opal/types";
const SvgScissors = ({ size, ...props }: IconProps) => (
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
      d="M13.33333 2.66667L8 8M9.64667 9.65333L13.33333 13.33333M8 8L5.41421 5.41421M8 8L5.41421 10.58579M5.41421 5.41421C5.77615 5.05228 6 4.55228 6 4C6 2.89543 5.10457 2 4 2C2.89543 2 2 2.89543 2 4C2 5.10457 2.89543 6 4 6C4.55228 6 5.05228 5.77615 5.41421 5.41421ZM5.41421 10.58579C5.05228 10.22385 4.55228 10 4 10C2.89543 10 2 10.89543 2 12C2 13.10457 2.89543 14 4 14C5.10457 14 6 13.10457 6 12C6 11.44772 5.77615 10.94772 5.41421 10.58579Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgScissors;
