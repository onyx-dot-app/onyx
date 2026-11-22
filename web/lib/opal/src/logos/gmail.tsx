import React from "react";
import type { IconProps } from "@opal/types";

const SvgGmail = ({ size, ...props }: IconProps) => {
  const id = React.useId();
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <path
        d="M12.021 7.1777V13.1455C12.021 13.4083 12.2407 13.628 12.5035 13.628H14.1119C14.6448 13.628 15.0769 13.1959 15.0769 12.663V3.90366C15.0769 4.33645 14.8894 4.76653 14.5322 5.06683L12.021 7.1777Z"
        fillRule="evenodd"
        clipRule="evenodd"
        fill={`url(#${id}-paint0)`}
      />
      <path
        d="M3.43426 2.7276C2.78825 2.1846 1.82442 2.26808 1.28143 2.91409C1.03907 3.20239 0.923077 3.55402 0.923077 3.9033C0.923077 4.33658 1.11025 4.76583 1.46792 5.06651L3.97902 7.17744L7.58608 10.2097C7.70201 10.3071 7.8486 10.3605 8.00004 10.3605C8.15148 10.3605 8.29807 10.3071 8.414 10.2097L12.021 7.1777L14.5322 5.06683C14.8894 4.76653 15.0769 4.33645 15.0769 3.90366C15.0769 3.5539 14.9613 3.20322 14.7186 2.91449C14.1756 2.26856 13.2117 2.1846 12.5658 2.7276L8 6.56554L3.43426 2.7276Z"
        fill={`url(#${id}-paint1)`}
      />
      <path
        d="M0.923077 12.663C0.923077 13.1959 1.35517 13.628 1.88811 13.628H3.4965C3.75931 13.628 3.97902 13.4083 3.97902 13.1455V7.17744L1.46792 5.06651C1.11025 4.76583 0.923077 4.33658 0.923077 3.9033V12.663Z"
        fill="#FC413D"
      />
      <defs>
        <linearGradient
          id={`${id}-paint0`}
          x1={13.5489}
          y1={3.8168}
          x2={13.5489}
          y2={13.628}
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#60D673" />
          <stop offset={0.17} stopColor="#42C868" />
          <stop offset={0.39} stopColor="#0EBC5F" />
          <stop offset={0.62} stopColor="#00A9BB" />
          <stop offset={0.86} stopColor="#3C90FF" />
          <stop offset={1} stopColor="#3186FF" />
        </linearGradient>
        <linearGradient
          id={`${id}-paint1`}
          x1={0.923077}
          y1={3.9881}
          x2={15.0769}
          y2={3.9881}
          gradientUnits="userSpaceOnUse"
        >
          <stop offset={0.08} stopColor="#FF63A0" />
          <stop offset={0.3} stopColor="#FC413D" />
          <stop offset={0.5} stopColor="#FC413D" />
          <stop offset={0.65} stopColor="#FC413D" />
          <stop offset={0.72} stopColor="#FC5C30" />
          <stop offset={0.86} stopColor="#FEB10C" />
          <stop offset={0.91} stopColor="#FEC700" />
          <stop offset={0.96} stopColor="#FFDB0F" />
        </linearGradient>
      </defs>
    </svg>
  );
};

export default SvgGmail;
