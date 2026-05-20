import type { IconProps } from "@opal/types";
const SvgNomic = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M35.858 6.31995H46V45.6709H35.6146C32.0852 36.8676 25.1481 27.7804 15.7363 24.8189V6.31995H25.4726C26.5274 12.7296 30.1618 18.3744 35.858 21.6546V6.31995Z"
      fill="var(--text-05)"
    />
    <path
      d="M15.7363 24.8189V45.6709H6L6 30.0927C9.05968 27.6167 11.9635 25.8737 15.7363 24.8189Z"
      fill="var(--text-05)"
    />
  </svg>
);
export default SvgNomic;
