import type { IconProps } from "@opal/types";
const SvgFullWidth = ({ size, ...props }: IconProps) => (
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
      d="M5.5 10L3.5 7.99998L5.5 6M3.5 7.99998H12.5M10.5 10L12.5 7.99998L10.5 6"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
    <path
      d="M13.336 2.67L2.66 2.66992C1.92545 2.66992 1.32998 3.26538 1.32999 3.99992L1.33 12.0099C1.33 12.7445 1.92546 13.3399 2.66 13.3399H13.336C14.0705 13.3399 14.666 12.7445 14.666 12.0099V4C14.666 3.26547 14.0705 2.67001 13.336 2.67Z"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);
export default SvgFullWidth;
