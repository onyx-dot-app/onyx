import type { SVGProps } from "react";

const SvgMinus = ({
  size,
  ...props
}: SVGProps<SVGSVGElement> & { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 16 16"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path d="M4 8H12" strokeWidth={1.5} strokeLinecap="round" />
  </svg>
);

export default SvgMinus;
