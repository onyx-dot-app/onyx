import type { IconProps } from "@opal/types";
const SvgMicrosoft = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 52 52"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M5 5H25V25H5V5Z" fill="#F35325" />
    <path d="M27 5H47V25H27V5Z" fill="#81BC06" />
    <path d="M5 27H25V47H5V27Z" fill="#05A6F0" />
    <path d="M27 27H47V47H27V27Z" fill="#FFBA08" />
  </svg>
);
export default SvgMicrosoft;
