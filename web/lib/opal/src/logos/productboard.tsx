import type { IconProps } from "@opal/types";
const SvgProductboard = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M19.9991 25.9997L35.9983 41.7494H4L19.9991 25.9997Z"
      fill="#FF2638"
    />
    <path d="M4 10.25L19.9991 25.9997L35.9983 10.25H4Z" fill="#FFC600" />
    <path
      d="M19.9991 25.9997L35.9983 41.7494L52 25.9997L35.9983 10.25L19.9991 25.9997Z"
      fill="#0079F2"
    />
  </svg>
);
export default SvgProductboard;
