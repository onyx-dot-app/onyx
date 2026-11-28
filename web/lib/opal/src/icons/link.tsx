import type { IconProps } from "@opal/types";
const SvgLink = ({ size, ...props }: IconProps) => (
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
      d="M7 4.40971L8.45903 2.95068C9.06184 2.34787 9.90168 2 10.7542 2C11.6067 2 12.4465 2.34787 13.0493 2.95068C13.6521 3.55349 14 4.39333 14 5.24583C14 6.09832 13.6521 6.93816 13.0493 7.54097L11.5903 9M9 11.5903L7.54097 13.0493C6.93817 13.6521 6.09832 14 5.24583 14C4.38498 14 3.55939 13.658 2.95068 13.0493C2.34197 12.4406 2 11.615 2 10.7542C2 9.89333 2.34197 9.06774 2.95068 8.45903L4.40971 7M6 10L10 6"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgLink;
