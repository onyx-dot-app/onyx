import type { IconProps } from "@opal/types";
const SvgEndOfLine = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 120 120"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M67.5 33.75H88.125C93.3027 33.75 97.5 29.5527 97.5 24.375C97.5 19.1973 93.3027 15 88.125 15H76.875C71.6973 15 67.5 19.1973 67.5 24.375V33.75ZM67.5 33.75H15M67.5 33.75V82.5"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M30 82.5H105"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M41.25 93.75H93.75"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M52.5 105H82.5"
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgEndOfLine;
