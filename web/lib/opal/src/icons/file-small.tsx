import type { IconProps } from "@opal/types";
const SvgFileSmall = ({ size, ...props }: IconProps) => (
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
      d="M8.75 4.75H5.75001C5.47386 4.75 5.25001 4.97386 5.25001 5.25V10.75C5.25001 11.0261 5.47386 11.25 5.75001 11.25H10.25C10.5261 11.25 10.75 11.0261 10.75 10.75V6.75M8.75 4.75L10.75 6.75M8.75 4.75V6.75H10.75"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFileSmall;
