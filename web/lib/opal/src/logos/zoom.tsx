import type { IconProps } from "@opal/types";

const SvgZoom = ({ size, ...props }: IconProps) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 26 26"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    {...props}
  >
    <path
      d="M24.2304 25.6335H3.68241C2.32724 25.6335 1.02664 24.9286 0.410657 23.7222C-0.314884 22.3395 -0.0410631 20.6856 1.05407 19.6012L15.3596 5.43581H5.10607C2.28604 5.43581 0 3.17212 0 0.379697H18.9325C20.2878 0.379697 21.5882 1.08445 22.2043 2.29089C22.9298 3.6735 22.656 5.32733 21.5609 6.41174L7.2554 20.5773H19.1106C21.9306 20.5773 24.2167 22.8411 24.2167 25.6335H24.2304Z"
      fill="#0B5CFF"
    />
  </svg>
);

export default SvgZoom;
