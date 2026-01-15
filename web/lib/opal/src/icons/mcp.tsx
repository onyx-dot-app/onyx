import type { IconProps } from "@opal/types";

const SvgMcp = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 14 15"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    stroke="currentColor"
    {...props}
  >
    <path
      d="M7.21111 3.25011L4.28535 6.17584C3.30914 7.15205 3.30914 8.7348 4.28535 9.71101C5.26155 10.6872 6.8443 10.6872 7.82051 9.71101L10.7463 6.78528M0.75 6.17566L5.44353 1.48216C6.41974 0.505948 8.00249 0.505947 8.9787 1.48216C9.95491 2.45837 9.95491 4.04111 8.9787 5.01732M8.9787 5.01732L6.05294 7.94306M8.9787 5.01732C9.95491 4.04111 11.538 4.04148 12.5142 5.01769C13.4904 5.9939 13.4904 7.57665 12.5142 8.55286L8.17457 12.8932C7.97933 13.0884 7.97934 13.405 8.17459 13.6003L8.82434 14.25"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default SvgMcp;
