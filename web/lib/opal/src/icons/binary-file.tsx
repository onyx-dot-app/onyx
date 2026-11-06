import type { IconProps } from "@opal/types";
const SvgBinaryFile = ({ size, ...props }: IconProps) => (
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
      d="M5.5 13.5V9.25003M10.5 6.75003V2.5M12.67 14C13.4045 14 14 13.4045 14 12.67V3.33C14 2.59546 13.4045 2 12.67 2M3.33 14C2.59546 14 2 13.4045 2 12.67V3.33C2 2.59546 2.59546 2 3.33 2M8.25 4C8.25 3.17157 7.57843 2.5 6.75 2.5C5.92157 2.5 5.25 3.17157 5.25 4V5.25003C5.25 6.07846 5.92157 6.75003 6.75 6.75003C7.57843 6.75003 8.25 6.07846 8.25 5.25003V4ZM9.25 9.25003C8.42157 9.25003 7.75 9.9216 7.75 10.75V12C7.75 12.8284 8.42157 13.5 9.25 13.5C10.0784 13.5 10.75 12.8284 10.75 12V10.75C10.75 9.9216 10.0784 9.25003 9.25 9.25003Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgBinaryFile;
