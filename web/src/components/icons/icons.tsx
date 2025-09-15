"use client";

import {
  Trash,
  XSquare,
  LinkBreak,
  Link,
  Plug,
  Brain,
  Question,
  Gear,
  ArrowSquareOut,
} from "@phosphor-icons/react";
import {
  FiChevronsDown,
  FiChevronsUp,
  FiEdit2,
  FiClipboard,
  FiFile,
  FiGlobe,
  FiThumbsDown,
  FiThumbsUp,
  FiChevronDown,
  FiChevronUp,
  FiAlertCircle,
  FiChevronRight,
  FiChevronLeft,
  FiAlertTriangle,
  FiCopy,
  FiCpu,
  FiInfo,
  FiBarChart2,
  FiMail,
} from "react-icons/fi";
import { SiBookstack } from "react-icons/si";
import { StaticImageData } from "next/image";
import outlinePNG from "../../../public/Outline.png";
import jiraSVG from "../../../public/Jira.svg";
import confluenceSVG from "../../../public/Confluence.svg";
import deepseekSVG from "../../../public/Deepseek.svg";
import openAISVG from "../../../public/Openai.svg";
import amazonSVG from "../../../public/Amazon.svg";
import geminiSVG from "../../../public/Gemini.svg";
import metaSVG from "../../../public/Meta.svg";
import mistralSVG from "../../../public/Mistral.svg";
import qwenSVG from "../../../public/Qwen.svg";
import openSourceIcon from "../../../public/OpenSource.png";
import litellmIcon from "../../../public/litellm.png";
import azureIcon from "../../../public/Azure.png";
import asanaIcon from "../../../public/Asana.png";
import anthropicSVG from "../../../public/Anthropic.svg";
import nomicSVG from "../../../public/nomic.svg";
import microsoftIcon from "../../../public/microsoft.png";
import microsoftSVG from "../../../public/Microsoft.svg";
import mixedBreadSVG from "../../../public/Mixedbread.png";
import OCIStorageSVG from "../../../public/OCI.svg";
import googleCloudStorageIcon from "../../../public/GoogleCloudStorage.png";
import guruIcon from "../../../public/Guru.svg";
import gongIcon from "../../../public/Gong.png";
import zulipIcon from "../../../public/Zulip.png";
import linearIcon from "../../../public/Linear.png";
import hubSpotIcon from "../../../public/HubSpot.png";
import document360Icon from "../../../public/Document360.png";
import googleSitesIcon from "../../../public/GoogleSites.png";
import zendeskIcon from "../../../public/Zendesk.svg";
import dropboxIcon from "../../../public/Dropbox.png";
import egnyteIcon from "../../../public/Egnyte.png";
import slackIcon from "../../../public/Slack.png";
import discordIcon from "../../../public/discord.png";
import airtableIcon from "../../../public/Airtable.svg";
import s3Icon from "../../../public/S3.png";
import r2Icon from "../../../public/r2.png";
import salesforceIcon from "../../../public/Salesforce.png";
import freshdeskIcon from "../../../public/Freshdesk.png";
import firefliesIcon from "../../../public/Fireflies.png";
import gitbookDarkIcon from "../../../public/GitBookDark.png";
import gitbookLightIcon from "../../../public/GitBookLight.png";
import sharepointIcon from "../../../public/Sharepoint.png";
import teamsIcon from "../../../public/Teams.png";
import mediawikiIcon from "../../../public/MediaWiki.svg";
import wikipediaIcon from "../../../public/Wikipedia.png";
import discourseIcon from "../../../public/Discourse.png";
import clickupIcon from "../../../public/Clickup.svg";
import cohereIcon from "../../../public/Cohere.svg";
import googleIcon from "../../../public/Google.png";
import xenforoIcon from "../../../public/Xenforo.svg";
import highspotIcon from "../../../public/Highspot.png";
import bitbucketIcon from "../../../public/Bitbucket.svg";
import { FaGithub, FaRobot } from "react-icons/fa";
import Image from "next/image";
import { cn } from "@/lib/utils";

export interface IconProps {
  size?: number;
  className?: string;
}

export interface LogoIconProps extends IconProps {
  src: string | StaticImageData;
}

export type OnyxIconType = (props: IconProps) => JSX.Element;

export const OpenAIISVG = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <svg
    fill="currentColor"
    width={size}
    style={{ width: `${size}px`, height: `${size}px` }}
    height={size}
    className={`w-[${size}px] h-[${size}px] ` + className}
    viewBox="0 0 24 24"
    role="img"
    xmlns="http://www.w3.org/2000/svg"
  >
    <path
      fill="currentColor"
      d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"
    />
  </svg>
);

export const LogoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
  src,
}: LogoIconProps) => (
  <Image
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
    src={src}
    alt="Logo"
    width="96"
    height="96"
  />
);

export const AssistantsIconSkeleton = ({
  size,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M8.88 21.25h9.87a2.5 2.5 0 0 0 2.5-2.5v-3.63a2.5 2.5 0 0 0-2.5-2.48h-1.27m-6.1 6.09l6.1-6.11l1.87-1.87a2.49 2.49 0 0 0 0-3.53l-2.57-2.57a2.49 2.49 0 0 0-3.53 0l-1.87 1.87" />
        <path d="M8.88 2.75H5.25a2.5 2.5 0 0 0-2.5 2.5v13.5a2.5 2.5 0 0 0 2.5 2.5h3.63a2.5 2.5 0 0 0 2.5-2.5V5.25a2.5 2.5 0 0 0-2.5-2.5" />
        <path d="M7.065 18.594a1.594 1.594 0 1 0 0-3.188a1.594 1.594 0 0 0 0 3.188" />
      </g>
    </svg>
  );
};

export const LightBulbIcon = ({
  size,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M12 18v-5.25m0 0a6.01 6.01 0 0 0 1.5-.189m-1.5.189a6.01 6.01 0 0 1-1.5-.189m3.75 7.478a12.06 12.06 0 0 1-4.5 0m3.75 2.383a14.406 14.406 0 0 1-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 1 0-7.517 0c.85.493 1.509 1.333 1.509 2.316V18"
      />
    </svg>
  );
};

export const AssistantsIcon = ({
  size,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M20.893 12.84a3.23 3.23 0 0 0-1.796-.91l.639-.64c.3-.304.537-.664.698-1.06a3.207 3.207 0 0 0 0-2.48a3.16 3.16 0 0 0-.698-1.06l-2.564-2.56a2.993 2.993 0 0 0-.997-.71a3.244 3.244 0 0 0-2.484 0a3.113 3.113 0 0 0-.998.7l-.638.64a3.242 3.242 0 0 0-1.086-1.973A3.227 3.227 0 0 0 8.863 2H5.242a3.248 3.248 0 0 0-2.29.955A3.264 3.264 0 0 0 2 5.25v13.5c0 .862.342 1.689.95 2.298c.608.61 1.432.952 2.292.952h13.466a3.254 3.254 0 0 0 2.295-1A3.239 3.239 0 0 0 22 18.7v-3.58a3.246 3.246 0 0 0-1.107-2.28M6.928 19.35a2.34 2.34 0 0 1-2.166-1.45a2.356 2.356 0 0 1 .508-2.562A2.341 2.341 0 0 1 9.272 17a2.344 2.344 0 0 1-2.344 2.35m5.057-12.52l1.646-1.65c.162-.163.356-.293.569-.38c.426-.17.9-.17 1.326 0c.21.093.402.221.569.38l2.563 2.57a2 2 0 0 1 .38.57a1.788 1.788 0 0 1 0 1.34c-.09.21-.219.4-.38.56l-6.673 6.7z"
      />
      <path
        fill="currentColor"
        d="M7.795 17a.852.852 0 0 1-1.007.845a.847.847 0 0 1-.671-.665a.852.852 0 0 1 .83-1.02a.847.847 0 0 1 .848.84"
      />
    </svg>
  );
};

<svg
  xmlns="http://www.w3.org/2000/svg"
  width="200"
  height="200"
  viewBox="0 0 24 24"
>
  <g fill="none" stroke="currentColor" strokeWidth="1.5">
    <path
      strokeLinecap="round"
      d="M21.483 19c-.04.936-.165 1.51-.569 1.914c-.586.586-1.528.586-3.414.586c-1.886 0-2.828 0-3.414-.586c-.586-.586-.586-1.528-.586-3.414v-2c0-1.886 0-2.828.586-3.414c.586-.586 1.528-.586 3.414-.586c1.886 0 2.828 0 3.414.586c.532.531.581 1.357.585 2.914"
    />
    <path d="M2 8.5c0 1.886 0 2.828.586 3.414c.586.586 1.528.586 3.414.586c1.886 0 2.828 0 3.414-.586C10 11.328 10 10.386 10 8.5v-2c0-1.886 0-2.828-.586-3.414C8.828 2.5 7.886 2.5 6 2.5c-1.886 0-2.828 0-3.414.586C2 3.672 2 4.614 2 6.5v2Z" />
    <path
      strokeLinecap="round"
      d="M15.5 2.513c-.327.017-.562.055-.765.14a2 2 0 0 0-1.083 1.082c-.152.367-.152.833-.152 1.765c0 .932 0 1.398.152 1.765a2 2 0 0 0 1.083 1.083c.367.152.833.152 1.765.152h2c.932 0 1.398 0 1.765-.152a2 2 0 0 0 1.083-1.083c.152-.367.152-.833.152-1.765c0-.932 0-1.398-.152-1.765a2 2 0 0 0-1.083-1.083c-.204-.084-.438-.122-.765-.139"
    />
    <path d="M2 18.5c0 .932 0 1.398.152 1.765a2 2 0 0 0 1.083 1.083c.367.152.833.152 1.765.152h2c.932 0 1.398 0 1.765-.152a2 2 0 0 0 1.083-1.083C10 19.898 10 19.432 10 18.5c0-.932 0-1.398-.152-1.765a2 2 0 0 0-1.083-1.083C8.398 15.5 7.932 15.5 7 15.5H5c-.932 0-1.398 0-1.765.152a2 2 0 0 0-1.083 1.083C2 17.102 2 17.568 2 18.5Z" />
  </g>
</svg>;

export const ConfigureIcon = ({
  size,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1.5">
        <path
          strokeLinecap="round"
          d="M21.483 19c-.04.936-.165 1.51-.569 1.914c-.586.586-1.528.586-3.414.586c-1.886 0-2.828 0-3.414-.586c-.586-.586-.586-1.528-.586-3.414v-2c0-1.886 0-2.828.586-3.414c.586-.586 1.528-.586 3.414-.586c1.886 0 2.828 0 3.414.586c.532.531.581 1.357.585 2.914"
        />
        <path d="M2 8.5c0 1.886 0 2.828.586 3.414c.586.586 1.528.586 3.414.586c1.886 0 2.828 0 3.414-.586C10 11.328 10 10.386 10 8.5v-2c0-1.886 0-2.828-.586-3.414C8.828 2.5 7.886 2.5 6 2.5c-1.886 0-2.828 0-3.414.586C2 3.672 2 4.614 2 6.5v2Z" />
        <path
          strokeLinecap="round"
          d="M15.5 2.513c-.327.017-.562.055-.765.14a2 2 0 0 0-1.083 1.082c-.152.367-.152.833-.152 1.765c0 .932 0 1.398.152 1.765a2 2 0 0 0 1.083 1.083c.367.152.833.152 1.765.152h2c.932 0 1.398 0 1.765-.152a2 2 0 0 0 1.083-1.083c.152-.367.152-.833.152-1.765c0-.932 0-1.398-.152-1.765a2 2 0 0 0-1.083-1.083c-.204-.084-.438-.122-.765-.139"
        />
        <path d="M2 18.5c0 .932 0 1.398.152 1.765a2 2 0 0 0 1.083 1.083c.367.152.833.152 1.765.152h2c.932 0 1.398 0 1.765-.152a2 2 0 0 0 1.083-1.083C10 19.898 10 19.432 10 18.5c0-.932 0-1.398-.152-1.765a2 2 0 0 0-1.083-1.083C8.398 15.5 7.932 15.5 7 15.5H5c-.932 0-1.398 0-1.765.152a2 2 0 0 0-1.083 1.083C2 17.102 2 17.568 2 18.5Z" />
      </g>
    </svg>
  );
};

export const defaultTailwindCSS = "my-auto flex flex-shrink-0 text-default";
export const defaultTailwindCSSBlue = "my-auto flex flex-shrink-0 text-link";

export const ColorSlackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={slackIcon} />;
};

export const ColorDiscordIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={discordIcon} />;
};

export const LiteLLMIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={litellmIcon} />;
};

export const OpenSourceIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={openSourceIcon} />;
};

export const MixedBreadIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={mixedBreadSVG} />;
};

export const NomicIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={nomicSVG} />;
};

export const MicrosoftIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={microsoftIcon} />;
};

export const AnthropicIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={anthropicSVG} />;
};

export const LeftToLineIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M3 19V5m10 1l-6 6l6 6m-6-6h14"
      />
    </svg>
  );
};

export const RightToLineIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M17 12H3m8 6l6-6l-6-6m10-1v14"
      />
    </svg>
  );
};

export const PlusCircleIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M12 2.25c-5.385 0-9.75 4.365-9.75 9.75s4.365 9.75 9.75 9.75s9.75-4.365 9.75-9.75S17.385 2.25 12 2.25ZM12.75 9a.75.75 0 0 0-1.5 0v2.25H9a.75.75 0 0 0 0 1.5h2.25V15a.75.75 0 0 0 1.5 0v-2.25H15a.75.75 0 0 0 0-1.5h-2.25V9Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const AppSearchIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <path
        d="M1.00261 7.5H2.5M1 4H3.25M1.00261 11H3.25M15 13L12.682 10.682M12.682 10.682C13.4963 9.86764 14 8.74264 14 7.5C14 5.01472 11.9853 3 9.49999 3C7.01472 3 5 5.01472 5 7.5C5 9.98528 7.01472 12 9.49999 12C10.7426 12 11.8676 11.4963 12.682 10.682Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const DisableIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <g clipPath="url(#clip0_295_7943)">
        <path
          d="M3.28659 3.28665L12.7133 12.7133M14.6666 7.99998C14.6666 11.6819 11.6818 14.6666 7.99992 14.6666C4.31802 14.6666 1.33325 11.6819 1.33325 7.99998C1.33325 4.31808 4.31802 1.33331 7.99992 1.33331C11.6818 1.33331 14.6666 4.31808 14.6666 7.99998Z"
          stroke="currentColor"
          strokeOpacity="0.4"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <defs>
        <clipPath id="clip0_295_7943">
          <rect width="16" height="16" fill="white" />
        </clipPath>
      </defs>
    </svg>
  );
};

export const MoreActionsIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <path
        d="M3.06 6.24449L5.12 4.12225L3.06 2.00001M11.5501 14L14 11.5501M14 11.5501L11.5501 9.10017M14 11.5501H9.75552M4.12224 9.09889L6.24448 10.3242V12.7747L4.12224 14L2 12.7747V10.3242L4.12224 9.09889ZM14 4.12225C14 5.29433 13.0498 6.24449 11.8778 6.24449C10.7057 6.24449 9.75552 5.29433 9.75552 4.12225C9.75552 2.95017 10.7057 2.00001 11.8778 2.00001C13.0498 2.00001 14 2.95017 14 4.12225Z"
        stroke="currentColor"
        strokeOpacity="0.4"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const SlidersVerticalIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g clipPath="url(#clip0_16_2627)">
        <path
          d="M2.66666 14V9.33333M2.66666 6.66667V2M7.99999 14V8M7.99999 5.33333V2M13.3333 14V10.6667M13.3333 8V2M0.666656 9.33333H4.66666M5.99999 5.33333H9.99999M11.3333 10.6667H15.3333"
          stroke="currentColor"
          strokeOpacity="0.8"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <defs>
        <clipPath id="clip0_16_2627">
          <rect width="16" height="16" fill="white" />
        </clipPath>
      </defs>
    </svg>
  );
};

export const PlugIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Plug size={size} className={className} />;
};

export const ExtendIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M16.75 11.989a1.82 1.82 0 0 1-.57 1.36l-6.82 6.1a1.27 1.27 0 0 1-.65.31h-.19a1.3 1.3 0 0 1-.52-.1a1.23 1.23 0 0 1-.54-.47a1.19 1.19 0 0 1-.21-.68v-13a1.2 1.2 0 0 1 .21-.69a1.23 1.23 0 0 1 1.25-.56c.24.039.464.143.65.3l6.76 6.09c.19.162.344.363.45.59c.114.234.175.49.18.75"
      />
    </svg>
  );
};
export const GearIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Gear size={size} className={className} />;
};

export const ArrowSquareOutIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <ArrowSquareOut size={size} className={className} />;
};

export const TrashIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Trash size={size} className={className} />;
};

export const LinkBreakIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LinkBreak size={size} className={className} />;
};

export const LinkIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Link size={size} className={className} />;
};

export const XSquareIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <XSquare size={size} className={className} />;
};

export const FileIcon = ({
  size = 16,
  className = defaultTailwindCSSBlue,
}: IconProps) => {
  return <FiFile size={size} className={className} />;
};

export const FileIcon2 = ({
  size = 16,
  className = defaultTailwindCSSBlue,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12.5 12.5a1 1 0 0 1-1 1h-9a1 1 0 0 1-1-1v-11a1 1 0 0 1 1-1h5l5 5Zm-8-8h2m-2 3h5m-5 3h5"
      />
    </svg>
  );
};

export const FilterIcon = ({ size = 16 }: IconProps) => {
  return (
    <svg
      width={size}
      height={size - 2}
      viewBox={`0 0 ${size} ${size - 2}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M14.6667 1H1.33334L6.66668 7.30667V11.6667L9.33334 13V7.30667L14.6667 1Z"
        stroke="currentColor"
        strokeOpacity="0.8"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const FileUploadIcon = ({ size = 16 }: IconProps) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <g clipPath="url(#clip0_16_2625)">
        <path
          d="M7.99999 5.33333V10.6667M5.33333 7.99999H10.6667M14.6667 7.99999C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 7.99999C1.33333 4.3181 4.3181 1.33333 7.99999 1.33333C11.6819 1.33333 14.6667 4.3181 14.6667 7.99999Z"
          stroke="currentColor"
          strokeOpacity="0.8"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </g>
      <defs>
        <clipPath id="clip0_16_2625">
          <rect width="16" height="16" fill="white" />
        </clipPath>
      </defs>
    </svg>
  );
};

export const InfoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiInfo size={size} className={className} />;
};

export const QuestionIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Question size={size} className={className} />;
};

export const BrainIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Brain size={size} className={className} />;
};

export const EditIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiEdit2 size={size} className={className} />;
};

export const ThumbsDownIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiThumbsDown size={size} className={className} />;
};

export const ChevronsUpIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiChevronsUp size={size} className={className} />;
};

export const ChevronsDownIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiChevronsDown size={size} className={className} />;
};

export const ChevronUpIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiChevronUp size={size} className={className} />;
};

export const ChevronDownIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiChevronDown size={size} className={className} />;
};

export const ChevronRightIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiChevronRight size={size} className={className} />;
};

export const ChevronLeftIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiChevronLeft size={size} className={className} />;
};

export const XIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M18 6L6 18M6 6l12 12"
      />
    </svg>
  );
};

export const UndoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px]` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M3.464 3.464C2 4.93 2 7.286 2 12c0 4.714 0 7.071 1.464 8.535C4.93 22 7.286 22 12 22c4.714 0 7.071 0 8.535-1.465C22 19.072 22 16.715 22 12c0-4.714 0-7.071-1.465-8.536C19.072 2 16.714 2 12 2S4.929 2 3.464 3.464Zm5.795 4.51A.75.75 0 1 0 8.24 6.872L5.99 8.949a.75.75 0 0 0 0 1.102l2.25 2.077a.75.75 0 1 0 1.018-1.102l-.84-.776h5.62c.699 0 1.168 0 1.526.036c.347.034.507.095.614.164c.148.096.275.223.37.371c.07.106.13.267.165.614c.035.358.036.827.036 1.526c0 .7 0 1.169-.036 1.527c-.035.346-.095.507-.164.614a1.25 1.25 0 0 1-.371.37c-.107.07-.267.13-.614.165c-.358.035-.827.036-1.526.036H9.5a.75.75 0 1 0 0 1.5h4.576c.652 0 1.196 0 1.637-.044c.462-.046.89-.145 1.28-.397c.327-.211.605-.49.816-.816c.252-.39.351-.818.397-1.28c.044-.441.044-.985.044-1.637v-.075c0-.652 0-1.196-.044-1.637c-.046-.462-.145-.891-.397-1.28a2.748 2.748 0 0 0-.816-.817c-.39-.251-.818-.35-1.28-.396c-.44-.044-.985-.044-1.637-.044H8.418l.84-.776Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const BackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px]` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M9.32 3.5L4.11 8.71a1.214 1.214 0 0 0 0 1.724l5.21 5.209" />
        <path d="M20.249 20.5v-7.286a3.643 3.643 0 0 0-3.643-3.643H3.759" />
      </g>
    </svg>
  );
};

export const MagnifyingIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M9.965 11.026a5 5 0 1 1 1.06-1.06l2.755 2.754a.75.75 0 1 1-1.06 1.06zM10.5 7a3.5 3.5 0 1 1-7 0a3.5 3.5 0 0 1 7 0"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const ToggleDown = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const ToggleUp = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M11.78 9.78a.75.75 0 0 1-1.06 0L8 7.06L5.28 9.78a.75.75 0 0 1-1.06-1.06l3.25-3.25a.75.75 0 0 1 1.06 0l3.25 3.25a.75.75 0 0 1 0 1.06"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const BroomIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px]` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M18.221 19.643c.477-.903.942-1.937 1.24-2.98c.411-1.438.56-2.788.602-3.818l-1.552-1.552l-5.804-5.804l-1.552-1.552c-1.03.042-2.38.19-3.817.602c-1.045.298-2.078.763-2.981 1.24C2.1 6.97 1.427 9.71 2.497 11.807l.013.025l.7 1.15a23.338 23.338 0 0 0 7.808 7.809l1.15.699l.025.013c2.096 1.07 4.837.396 6.028-1.86Zm3.554-16.33a.77.77 0 0 0-1.088-1.088L19.012 3.9a4.877 4.877 0 0 0-5.718 0l1.109 1.109l4.588 4.588l1.109 1.109a4.877 4.877 0 0 0 0-5.718l1.675-1.675Z"
      />
    </svg>
  );
};

export const ChevronIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M15.25 2h-6.5A6.76 6.76 0 0 0 2 8.75v6.5A6.76 6.76 0 0 0 8.75 22h6.5A6.76 6.76 0 0 0 22 15.25v-6.5A6.76 6.76 0 0 0 15.25 2m-.23 10.77a2.109 2.109 0 0 1-.46.67l-3.68 3.68a1 1 0 0 1-1.41 0a1 1 0 0 1 0-1.41l3.68-3.68v-.12L9.5 8.3a1 1 0 1 1 1.4-1.43l3.67 3.59a2.069 2.069 0 0 1 .63 1.49a2.07 2.07 0 0 1-.18.82"
      />
    </svg>
  );
};

export const StarFeedback = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="m12.495 18.587l4.092 2.15a1.044 1.044 0 0 0 1.514-1.106l-.783-4.552a1.045 1.045 0 0 1 .303-.929l3.31-3.226a1.043 1.043 0 0 0-.575-1.785l-4.572-.657A1.044 1.044 0 0 1 15 7.907l-2.088-4.175a1.044 1.044 0 0 0-1.88 0L8.947 7.907a1.044 1.044 0 0 1-.783.575l-4.51.657a1.044 1.044 0 0 0-.584 1.785l3.309 3.226a1.044 1.044 0 0 1 .303.93l-.783 4.55a1.044 1.044 0 0 0 1.513 1.107l4.093-2.15a1.043 1.043 0 0 1 .991 0"
      />
    </svg>
  );
};

export const DislikeFeedback = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M5.75 2.75H4.568c-.98 0-1.775.795-1.775 1.776v8.284c0 .98.795 1.775 1.775 1.775h1.184c.98 0 1.775-.794 1.775-1.775V4.526c0-.98-.795-1.776-1.775-1.776" />
        <path d="m21.16 11.757l-1.42-7.101a2.368 2.368 0 0 0-2.367-1.906h-7.48a2.367 2.367 0 0 0-2.367 2.367v7.101a3.231 3.231 0 0 0 1.184 2.367l.982 5.918a.887.887 0 0 0 1.278.65l1.1-.543a3.551 3.551 0 0 0 1.87-4.048l-.496-1.965h5.396a2.368 2.368 0 0 0 2.32-2.84" />
      </g>
    </svg>
  );
};

export const LikeFeedback = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M5.75 9.415H4.568c-.98 0-1.775.794-1.775 1.775v8.284c0 .98.795 1.776 1.775 1.776h1.184c.98 0 1.775-.795 1.775-1.776V11.19c0-.98-.795-1.775-1.775-1.775" />
        <path d="m21.16 12.243l-1.42 7.101a2.367 2.367 0 0 1-2.367 1.906h-7.48a2.367 2.367 0 0 1-2.367-2.367v-7.101A3.231 3.231 0 0 1 8.71 9.415l.982-5.918a.888.888 0 0 1 1.278-.65l1.1.544a3.55 3.55 0 0 1 1.87 4.047l-.496 1.965h5.396a2.367 2.367 0 0 1 2.32 2.84" />
      </g>
    </svg>
  );
};

export const CheckmarkIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M20 6L9 17l-5-5"
      />
    </svg>
  );
};

export const ClipboardIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiClipboard size={size} className={className} />;
};

export const AlertIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiAlertCircle size={size} className={className} />;
};

export const TriangleAlertIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiAlertTriangle size={size} className={className} />;
};

export const CopyIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiCopy size={size} className={className} />;
};

export const CPUIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiCpu size={size} className={className} />;
};
export const ChatIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"></path>
    </svg>
  );
};

export const OnyxSparkleIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 16 16`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <path
        d="M4 2L8 4L12 2M12 14L8 12L4 14M2 12L4 7.99999L2 3.99999M14 3.99999L12 7.99999L14 12"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const SendIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M12 19V5m-7 7l7-7l7 7"
      />
    </svg>
  );
};

export const SearchIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      fill="none"
      strokeLinecap="round"
      strokeLinejoin="round"
      strokeWidth="2"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path>
    </svg>
  );
};

export const BellIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M12 1.25A7.75 7.75 0 0 0 4.25 9v.704a3.53 3.53 0 0 1-.593 1.958L2.51 13.385c-1.334 2-.316 4.718 2.003 5.35c.755.206 1.517.38 2.284.523l.002.005C7.567 21.315 9.622 22.75 12 22.75s4.433-1.435 5.202-3.487l.002-.005a28.472 28.472 0 0 0 2.284-.523c2.319-.632 3.337-3.35 2.003-5.35l-1.148-1.723a3.53 3.53 0 0 1-.593-1.958V9A7.75 7.75 0 0 0 12 1.25Zm3.376 18.287a28.46 28.46 0 0 1-6.753 0c.711 1.021 1.948 1.713 3.377 1.713c1.429 0 2.665-.692 3.376-1.713ZM5.75 9a6.25 6.25 0 1 1 12.5 0v.704c0 .993.294 1.964.845 2.79l1.148 1.723a2.02 2.02 0 0 1-1.15 3.071a26.96 26.96 0 0 1-14.187 0a2.021 2.021 0 0 1-1.15-3.07l1.15-1.724a5.03 5.03 0 0 0 .844-2.79V9Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const LightSettingsIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M12.132 15.404a3.364 3.364 0 1 0 0-6.728a3.364 3.364 0 0 0 0 6.728" />
        <path d="M20.983 15.094a9.43 9.43 0 0 1-1.802 3.1l-2.124-.482a7.245 7.245 0 0 1-2.801 1.56l-.574 2.079a9.462 9.462 0 0 1-1.63.149a9.117 9.117 0 0 1-2.032-.23l-.609-2.146a7.475 7.475 0 0 1-2.457-1.493l-2.1.54a9.357 9.357 0 0 1-1.837-3.33l1.55-1.722a7.186 7.186 0 0 1 .069-2.652L3.107 8.872a9.356 9.356 0 0 1 2.067-3.353l2.17.54A7.68 7.68 0 0 1 9.319 4.91l.574-2.124a8.886 8.886 0 0 1 2.17-.287c.585 0 1.17.054 1.745.16l.551 2.113c.83.269 1.608.68 2.296 1.217l2.182-.563a9.368 9.368 0 0 1 2.043 3.1l-1.48 1.607a7.405 7.405 0 0 1 .068 3.364z" />
      </g>
    </svg>
  );
};

export const EmailIcon = ({
  size = 24,
  className = defaultTailwindCSSBlue,
}: IconProps) => <FiMail size={size} className={className} />;

//  COMPANY LOGOS

export const LoopioIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon
    size={size}
    className={`${className} dark:invert`}
    src="/Loopio.png"
  />
);

export const NewIconTest = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/NewIconTest.svg" />
);

export const GitlabIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/Gitlab.png" />
);

export const GithubIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <FaGithub size={size} className={cn(className, "text-black")} />
);

export const BitbucketIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={bitbucketIcon} />
);

export const GlobeIcon = ({
  size = 16,
  className = defaultTailwindCSSBlue,
}: IconProps) => {
  return <FiGlobe size={size} className={className} />;
};

export const GlobeIcon2 = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 14 14"
    >
      <g stroke="#3B82F6" strokeLinecap="round" strokeLinejoin="round">
        <circle fill="transparent" cx="7" cy="7" r="6.5" />
        <path
          fill="transparent"
          d="M.5 7h13m-4 0A11.22 11.22 0 0 1 7 13.5A11.22 11.22 0 0 1 4.5 7A11.22 11.22 0 0 1 7 .5A11.22 11.22 0 0 1 9.5 7Z"
        />
      </g>
    </svg>
  );
};

export const GmailIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/Gmail.png" />
);

export const GoogleDriveIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/GoogleDrive.png" />
);

export const BookstackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <SiBookstack size={size} className={className} />;
};

export const OutlineIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon
    size={size + 4}
    className={`${className} -m-0.5`}
    src={outlinePNG}
  />
);

export const ConfluenceIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon
    size={size + 4}
    className={`${className} -m-0.5`}
    src={confluenceSVG}
  />
);

export const OCIStorageIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon
    size={size + 4}
    className={`${className} -m-0.5`}
    src={OCIStorageSVG}
  />
);

export const JiraIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size + 4} className={`${className} -m-0.5`} src={jiraSVG} />
);

export const ZulipIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={zulipIcon} />;

export const OpenAIIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={openAISVG} />;

export const GeminiIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={geminiSVG} />;

export const AmazonIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={amazonSVG} />;

export const MetaIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={metaSVG} />;

export const DeepseekIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={deepseekSVG} />
);

export const QwenIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={qwenSVG} />;

export const MicrosoftIconSVG = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={microsoftSVG} />
);

export const MistralIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={mistralSVG} />
);

export const VoyageIconSVG = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <svg
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 200 200"
    width="200"
    height="200"
  >
    <path
      d="M0 0 C18.56364691 14.8685395 31.52865476 35.60458591 34.68359375 59.39453125 C36.85790415 84.17093249 31.86661083 108.64738046 15.83569336 128.38696289 C-0.18749615 147.32766215 -21.13158775 159.50726579 -46 162 C-70.46026633 163.68595557 -94.53744209 157.16585411 -113.375 141.1875 C-131.5680983 125.12913912 -143.31327081 103.12304227 -145.16845703 78.79052734 C-146.52072106 52.74671426 -138.40787353 29.42123969 -121 10 C-120.39929688 9.30519531 -119.79859375 8.61039063 -119.1796875 7.89453125 C-88.7732111 -25.07872563 -34.66251161 -26.29920259 0 0 Z M-111 6 C-111.96292969 6.76441406 -112.92585938 7.52882813 -113.91796875 8.31640625 C-129.12066 21.0326872 -138.48510826 41.64930525 -141 61 C-142.57102569 86.19086606 -137.40498471 109.10013392 -120.54980469 128.68505859 C-106.05757815 144.84161953 -85.8110604 156.92053779 -63.68798828 158.12597656 C-39.72189393 158.83868932 -17.08757891 154.40601729 1.1875 137.6875 C3.15800523 135.82115685 5.07881363 133.91852176 7 132 C8.22396484 130.7934375 8.22396484 130.7934375 9.47265625 129.5625 C26.2681901 112.046746 31.70691205 89.639394 31.3125 66 C30.4579168 43.32505919 19.07700136 22.58412979 3 7 C-29.27431062 -21.68827611 -78.26536136 -21.67509486 -111 6 Z "
      fill="currentColor"
      transform="translate(155,29)"
    />
    <path
      d="M0 0 C2.62278901 2.33427271 3.96735488 4.64596813 5.4453125 7.81640625 C6.10080078 9.20956055 6.10080078 9.20956055 6.76953125 10.63085938 C7.21683594 11.59830078 7.66414063 12.56574219 8.125 13.5625 C8.58003906 14.53380859 9.03507812 15.50511719 9.50390625 16.50585938 C10.34430119 18.30011504 11.18198346 20.09564546 12.01611328 21.89282227 C12.65935931 23.27045415 13.32005367 24.64010734 14 26 C12.02 26 10.04 26 8 26 C6.515 22.535 6.515 22.535 5 19 C1.7 19 -1.6 19 -5 19 C-5.99 21.31 -6.98 23.62 -8 26 C-9.32 26 -10.64 26 -12 26 C-10.34176227 20.46347949 -7.92776074 15.38439485 -5.4375 10.1875 C-5.02564453 9.31673828 -4.61378906 8.44597656 -4.18945312 7.54882812 C-1.13502139 1.13502139 -1.13502139 1.13502139 0 0 Z M-1 8 C-3.2013866 11.80427492 -3.2013866 11.80427492 -4 16 C-1.69 16 0.62 16 3 16 C2.43260132 11.87026372 2.43260132 11.87026372 1 8 C0.34 8 -0.32 8 -1 8 Z "
      fill="currentColor"
      transform="translate(158,86)"
    />
    <path
      d="M0 0 C2.64453125 1.0234375 2.64453125 1.0234375 4.4453125 4.296875 C4.96971298 5.65633346 5.47294966 7.0241056 5.95703125 8.3984375 C6.22064453 9.08421875 6.48425781 9.77 6.75585938 10.4765625 C7.8687821 13.4482107 8.64453125 15.82826389 8.64453125 19.0234375 C9.30453125 19.0234375 9.96453125 19.0234375 10.64453125 19.0234375 C10.75667969 18.34925781 10.86882813 17.67507812 10.984375 16.98046875 C11.77373626 13.44469078 12.95952974 10.10400184 14.20703125 6.7109375 C14.44099609 6.06576172 14.67496094 5.42058594 14.91601562 4.75585938 C15.48900132 3.17722531 16.06632589 1.60016724 16.64453125 0.0234375 C17.96453125 0.0234375 19.28453125 0.0234375 20.64453125 0.0234375 C20.11164835 5.93359329 17.66052325 10.65458241 15.08203125 15.8984375 C14.65728516 16.77757813 14.23253906 17.65671875 13.79492188 18.5625 C12.75156566 20.71955106 11.70131241 22.87294038 10.64453125 25.0234375 C9.65453125 25.0234375 8.66453125 25.0234375 7.64453125 25.0234375 C6.36851794 22.52596727 5.09866954 20.02565814 3.83203125 17.5234375 C3.29739258 16.47929688 3.29739258 16.47929688 2.75195312 15.4140625 C0.37742917 10.70858383 -1.58321849 5.98797449 -3.35546875 1.0234375 C-2.35546875 0.0234375 -2.35546875 0.0234375 0 0 Z "
      fill="currentColor"
      transform="translate(23.35546875,86.9765625)"
    />
    <path
      d="M0 0 C4.56944444 2.13888889 4.56944444 2.13888889 6 5 C6.58094684 9.76376411 6.98189835 13.6696861 4.0625 17.625 C-0.08290736 19.4862033 -3.52913433 19.80184004 -8 19 C-11.18487773 17.20850628 -12.56721386 16.06753914 -13.9375 12.6875 C-14.04047475 8.25958558 -13.25966827 4.50191217 -10.375 1.0625 C-6.92547207 -0.48070986 -3.67744273 -0.55453501 0 0 Z M-7.66796875 3.21484375 C-9.3387892 5.45403713 -9.40271257 6.72874309 -9.375 9.5 C-9.38273437 10.2734375 -9.39046875 11.046875 -9.3984375 11.84375 C-8.90844456 14.49547648 -8.12507645 15.38331504 -6 17 C-3.17884512 17.42317323 -1.66049093 17.38718434 0.8125 15.9375 C2.65621741 12.92932949 2.30257262 10.44932782 2 7 C1.54910181 4.59436406 1.54910181 4.59436406 0 3 C-4.00690889 1.63330935 -4.00690889 1.63330935 -7.66796875 3.21484375 Z "
      fill="currentColor"
      transform="translate(58,93)"
    />
    <path
      d="M0 0 C0.91007812 0.00902344 1.82015625 0.01804687 2.7578125 0.02734375 C3.45648438 0.03894531 4.15515625 0.05054687 4.875 0.0625 C5.205 1.3825 5.535 2.7025 5.875 4.0625 C4.6375 3.815 3.4 3.5675 2.125 3.3125 C-1.0391959 2.93032359 -1.83705309 2.89394571 -4.6875 4.5625 C-6.71059726 8.08093001 -6.12332701 10.21181009 -5.125 14.0625 C-3.22744856 16.41223818 -3.22744856 16.41223818 0 16.1875 C0.94875 16.14625 1.8975 16.105 2.875 16.0625 C2.875 14.4125 2.875 12.7625 2.875 11.0625 C4.525 11.3925 6.175 11.7225 7.875 12.0625 C8.1875 14.375 8.1875 14.375 7.875 17.0625 C5.25185816 19.29988569 3.33979578 19.9932751 -0.0625 20.5 C-3.96030088 19.9431713 -6.06489651 18.49667323 -9.125 16.0625 C-11.6165904 12.3251144 -11.58293285 10.48918417 -11.125 6.0625 C-7.83836921 1.02299945 -5.86190884 -0.07515268 0 0 Z "
      fill="currentColor"
      transform="translate(113.125,92.9375)"
    />
    <path
      d="M0 0 C4.28705043 1.42901681 5.23208702 4.57025431 7.1875 8.375 C7.55552734 9.06078125 7.92355469 9.7465625 8.30273438 10.453125 C11 15.59744608 11 15.59744608 11 19 C9.35 19 7.7 19 6 19 C5.67 17.68 5.34 16.36 5 15 C2.03 14.67 -0.94 14.34 -4 14 C-4.33 15.65 -4.66 17.3 -5 19 C-5.99 19 -6.98 19 -8 19 C-7.38188466 14.44684052 -5.53234107 10.71540233 -3.4375 6.6875 C-2.9434668 5.71973633 -2.9434668 5.71973633 -2.43945312 4.73242188 C-1.63175745 3.15214772 -0.81662387 1.57567895 0 0 Z M0 6 C-0.33 7.65 -0.66 9.3 -1 11 C0.32 11 1.64 11 3 11 C2.34 9.35 1.68 7.7 1 6 C0.67 6 0.34 6 0 6 Z "
      fill="currentColor"
      transform="translate(90,93)"
    />
    <path
      d="M0 0 C3.63 0 7.26 0 11 0 C11 0.66 11 1.32 11 2 C8.69 2 6.38 2 4 2 C4 3.98 4 5.96 4 8 C5.98 8 7.96 8 10 8 C9.67 8.99 9.34 9.98 9 11 C7.68 11 6.36 11 5 11 C4.67 12.98 4.34 14.96 4 17 C7.465 16.505 7.465 16.505 11 16 C11 16.99 11 17.98 11 19 C7.37 19 3.74 19 0 19 C0 12.73 0 6.46 0 0 Z "
      fill="currentColor"
      transform="translate(124,93)"
    />
    <path
      d="M0 0 C2.25 -0.3125 2.25 -0.3125 5 0 C9 4.10810811 9 4.10810811 9 7 C9.78375 6.21625 10.5675 5.4325 11.375 4.625 C12.91666667 3.08333333 14.45833333 1.54166667 16 0 C16.99 0 17.98 0 19 0 C17.84356383 2.5056117 16.63134741 4.4803655 14.9375 6.6875 C12.52118995 10.81861073 12.20924288 14.29203528 12 19 C10.68 19 9.36 19 8 19 C8.00902344 18.443125 8.01804687 17.88625 8.02734375 17.3125 C7.78294047 11.0217722 5.92390505 8.0388994 1.49609375 3.62890625 C0 2 0 2 0 0 Z "
      fill="currentColor"
      transform="translate(64,93)"
    />
    <path
      d="M0 0 C1.32 0 2.64 0 4 0 C4 8.25 4 16.5 4 25 C2.68 25 1.36 25 0 25 C0 16.75 0 8.5 0 0 Z "
      fill="currentColor"
      transform="translate(173,87)"
    />
    <path
      d="M0 0 C0.66 0.33 1.32 0.66 2 1 C1.125 5.75 1.125 5.75 0 8 C1.093125 7.95875 2.18625 7.9175 3.3125 7.875 C7 8 7 8 10 10 C4.555 10.495 4.555 10.495 -1 11 C-1.99 13.31 -2.98 15.62 -4 18 C-5.32 18 -6.64 18 -8 18 C-6.65150163 13.64029169 -4.95092154 9.68658562 -2.875 5.625 C-2.33617187 4.56539063 -1.79734375 3.50578125 -1.2421875 2.4140625 C-0.83226562 1.61742188 -0.42234375 0.82078125 0 0 Z "
      fill="currentColor"
      transform="translate(154,94)"
    />
    <path
      d="M0 0 C0.66 0.33 1.32 0.66 2 1 C2 1.66 2 2.32 2 3 C1.34 3 0.68 3 0 3 C-0.05429959 4.74965358 -0.09292823 6.49979787 -0.125 8.25 C-0.14820313 9.22453125 -0.17140625 10.1990625 -0.1953125 11.203125 C0.00137219 14.0196498 0.55431084 15.60949036 2 18 C1.34 18.33 0.68 18.66 0 19 C-4.69653179 15.74855491 -4.69653179 15.74855491 -5.9375 12.6875 C-6.02161912 9.07037805 -5.30970069 6.36780178 -4 3 C-1.875 1.0625 -1.875 1.0625 0 0 Z "
      fill="currentColor"
      transform="translate(50,93)"
    />
    <path
      d="M0 0 C2.79192205 -0.05380578 5.5828141 -0.09357669 8.375 -0.125 C9.1690625 -0.14175781 9.963125 -0.15851563 10.78125 -0.17578125 C12.85492015 -0.19335473 14.92883241 -0.10335168 17 0 C17.66 0.66 18.32 1.32 19 2 C17 4 17 4 13.0859375 4.1953125 C11.51550649 4.18200376 9.94513779 4.15813602 8.375 4.125 C7.57320312 4.11597656 6.77140625 4.10695312 5.9453125 4.09765625 C3.96341477 4.07406223 1.98167019 4.03819065 0 4 C0 2.68 0 1.36 0 0 Z "
      fill="currentColor"
      transform="translate(92,187)"
    />
    <path
      d="M0 0 C0.99 0.33 1.98 0.66 3 1 C1.66666667 4.33333333 0.33333333 7.66666667 -1 11 C0.65 11 2.3 11 4 11 C4 11.33 4 11.66 4 12 C1.36 12.33 -1.28 12.66 -4 13 C-4.33 14.98 -4.66 16.96 -5 19 C-5.99 19 -6.98 19 -8 19 C-7.38188466 14.44684052 -5.53234107 10.71540233 -3.4375 6.6875 C-2.9434668 5.71973633 -2.9434668 5.71973633 -2.43945312 4.73242188 C-1.63175745 3.15214772 -0.81662387 1.57567895 0 0 Z "
      fill="currentColor"
      transform="translate(90,93)"
    />
    <path
      d="M0 0 C0.99 0 1.98 0 3 0 C2.43454163 3.95820859 1.19097652 6.6659053 -1 10 C-1.66 9.67 -2.32 9.34 -3 9 C-2.44271087 5.65626525 -1.64826111 2.96687001 0 0 Z "
      fill="currentColor"
      transform="translate(37,97)"
    />
    <path
      d="M0 0 C4.92127034 -0.16682272 8.50343896 -0.24828052 13 2 C9.60268371 4.09065618 6.95730595 4.42098999 3 4 C1.125 2.5625 1.125 2.5625 0 1 C0 0.67 0 0.34 0 0 Z "
      fill="currentColor"
      transform="translate(110,12)"
    />
    <path
      d="M0 0 C0 0.99 0 1.98 0 3 C-3.08888522 5.05925681 -3.70935927 5.2390374 -7.1875 5.125 C-9.0746875 5.063125 -9.0746875 5.063125 -11 5 C-10.67 4.34 -10.34 3.68 -10 3 C-7.96875 2.40234375 -7.96875 2.40234375 -5.5 1.9375 C-2.46226779 1.54135157 -2.46226779 1.54135157 0 0 Z "
      fill="currentColor"
      transform="translate(62,107)"
    />
    <path
      d="M0 0 C0.66 0.33 1.32 0.66 2 1 C1.25 5.75 1.25 5.75 -1 8 C-1.66 8 -2.32 8 -3 8 C-1.125 1.125 -1.125 1.125 0 0 Z "
      fill="currentColor"
      transform="translate(154,94)"
    />
    <path
      d="M0 0 C2.64 0 5.28 0 8 0 C8.33 1.32 8.66 2.64 9 4 C6.03 3.01 3.06 2.02 0 1 C0 0.67 0 0.34 0 0 Z "
      fill="currentColor"
      transform="translate(110,93)"
    />
    <path
      d="M0 0 C1.67542976 0.28604898 3.34385343 0.61781233 5 1 C4.67 2.32 4.34 3.64 4 5 C2.0625 4.6875 2.0625 4.6875 0 4 C-0.33 3.01 -0.66 2.02 -1 1 C-0.67 0.67 -0.34 0.34 0 0 Z "
      fill="currentColor"
      transform="translate(21,87)"
    />
  </svg>
);

export const GoogleIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={googleIcon} />
);

export const CohereIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={cohereIcon} />
);

export const GoogleStorageIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon
    size={size + 4}
    className={`${className} -m-0.5`}
    src={googleCloudStorageIcon}
  />
);

export const ProductboardIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/Productboard.png" />
);

export const AzureIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={azureIcon} />;

export const LinearIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={linearIcon} />
);

export const SlabIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/SlabLogo.png" />
);

export const NotionIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/Notion.png" />
);

export const GuruIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={guruIcon} />;

export const SalesforceIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={salesforceIcon} />
);

export const R2Icon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={r2Icon} />;

export const S3Icon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={s3Icon} />;

export const SharepointIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={sharepointIcon} />
);

export const TeamsIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={teamsIcon} />;

export const GongIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={gongIcon} />;

export const HubSpotIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={hubSpotIcon} />
);

export const Document360Icon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={document360Icon} />
);

export const GoogleSitesIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={googleSitesIcon} />
);
export const ZendeskIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    className="rounded-full overflow-visible dark:overflow-hidden flex items-center justify-center dark:bg-[#fff]/90"
    style={{ width: size, height: size }}
  >
    <LogoIcon
      size={
        typeof window !== "undefined" &&
        window.matchMedia("(prefers-color-scheme: dark)").matches
          ? size * 0.8
          : size
      }
      className={`${className}`}
      src={zendeskIcon}
    />
  </div>
);

export const DropboxIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={dropboxIcon} />
);

export const DiscourseIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={discourseIcon} />
);

export const AxeroIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src="/Axero.jpeg" />
);

export const ClickupIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={clickupIcon} />
);

export const MediaWikiIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={mediawikiIcon} />
);

export const WikipediaIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={wikipediaIcon} />
);

export const XenforoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={xenforoIcon} />
);

export const AsanaIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => <LogoIcon size={size} className={className} src={asanaIcon} />;

export const FreshdeskIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={freshdeskIcon} />
);

export const FirefliesIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <LogoIcon size={size} className={className} src={firefliesIcon} />
);

/* 
EE Icons
*/

export const BarChartIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiBarChart2 size={size} className={className} />;
};

//  Admin Icons

export const NotebookIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25"
      />
    </svg>
  );
};

export const NotebookIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M11.25 4.533A9.707 9.707 0 0 0 6 3a9.735 9.735 0 0 0-3.25.555a.75.75 0 0 0-.5.707v14.25a.75.75 0 0 0 1 .707A8.237 8.237 0 0 1 6 18.75c1.995 0 3.823.707 5.25 1.886V4.533Zm1.5 16.103A8.214 8.214 0 0 1 18 18.75c.966 0 1.89.166 2.75.47a.75.75 0 0 0 1-.708V4.262a.75.75 0 0 0-.5-.707A9.735 9.735 0 0 0 18 3a9.707 9.707 0 0 0-5.25 1.533v16.103Z"
      />
    </svg>
  );
};

export const ConnectorIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775a5.25 5.25 0 0 1 10.233-2.33a3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z"
      />
    </svg>
  );
};

export const ConnectorIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M4.5 13a3.5 3.5 0 0 1-1.41-6.705a3.5 3.5 0 0 1 6.63-2.171a2.5 2.5 0 0 1 3.197 3.018A3.001 3.001 0 0 1 12 13zm.72-5.03a.75.75 0 0 0 1.06 1.06l.97-.97v2.69a.75.75 0 0 0 1.5 0V8.06l.97.97a.75.75 0 1 0 1.06-1.06L8.53 5.72a.75.75 0 0 0-1.06 0z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const DocumentSetIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M22 9.885v7.7a3.85 3.85 0 0 1-2.373 3.542a3.8 3.8 0 0 1-1.467.288H5.83A3.82 3.82 0 0 1 2 17.585V6.425a3.82 3.82 0 0 1 3.83-3.84h3.08a3.87 3.87 0 0 1 3.2 1.71l.87 1.33a1 1 0 0 0 .36.32a.94.94 0 0 0 .47.12h4.35a3.79 3.79 0 0 1 2.71 1.11A3.85 3.85 0 0 1 22 9.885"
      />
    </svg>
  );
};

export const DocumentSetIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M21.25 9.883v7.698a3.083 3.083 0 0 1-3.083 3.083H5.833a3.083 3.083 0 0 1-3.083-3.083V6.419a3.083 3.083 0 0 1 3.083-3.083h3.084a3.083 3.083 0 0 1 2.57 1.377l.873 1.326a1.748 1.748 0 0 0 1.449.77h4.358a3.084 3.084 0 0 1 3.083 3.074"
      />
    </svg>
  );
};
export const BookmarkIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M17.593 3.322c1.1.128 1.907 1.077 1.907 2.185V21L12 17.25L4.5 21V5.507c0-1.108.806-2.057 1.907-2.185a48.507 48.507 0 0 1 11.186 0Z"
      />
    </svg>
  );
};
export const BookmarkIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        d="M3.75 2a.75.75 0 0 0-.75.75v10.5a.75.75 0 0 0 1.28.53L8 10.06l3.72 3.72a.75.75 0 0 0 1.28-.53V2.75a.75.75 0 0 0-.75-.75z"
      />
    </svg>
  );
};

export const BookIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 20 20"
    >
      <path
        fill="currentColor"
        d="M10.75 16.82A7.462 7.462 0 0 1 15 15.5a7.5 7.5 0 0 1 2.046.282a.75.75 0 0 0 .954-.722v-11a.75.75 0 0 0-.546-.721A9.006 9.006 0 0 0 15 3a8.963 8.963 0 0 0-4.25 1.065V16.82ZM9.25 4.065A8.963 8.963 0 0 0 5 3a9 9 0 0 0-2.454.339A.75.75 0 0 0 2 4.06v11a.75.75 0 0 0 .954.721A7.506 7.506 0 0 1 5 15.5c1.579 0 3.042.487 4.25 1.32V4.065Z"
      />
    </svg>
  );
};

export const ZoomInIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Zm3.75 11.625a2.625 2.625 0 1 1-5.25 0a2.625 2.625 0 0 1 5.25 0Z"
      />
    </svg>
  );
};

export const ZoomInIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 20 20"
    >
      <g fill="currentColor">
        <path d="M8 10a1.5 1.5 0 1 1 3 0a1.5 1.5 0 0 1-3 0Z" />
        <path
          fillRule="evenodd"
          d="M4.5 2A1.5 1.5 0 0 0 3 3.5v13A1.5 1.5 0 0 0 4.5 18h11a1.5 1.5 0 0 0 1.5-1.5V7.621a1.5 1.5 0 0 0-.44-1.06l-4.12-4.122A1.5 1.5 0 0 0 11.378 2H4.5Zm5 5a3 3 0 1 0 1.524 5.585l1.196 1.195a.75.75 0 1 0 1.06-1.06l-1.195-1.196A3 3 0 0 0 9.5 7Z"
          clipRule="evenodd"
        />
      </g>
    </svg>
  );
};

export const ThumbsUpIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M8.625 9.75a.375.375 0 1 1-.75 0a.375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0a.375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0a.375.375 0 0 1 .75 0Zm0 0h-.375m-13.5 3.01c0 1.6 1.123 2.994 2.707 3.227c1.087.16 2.185.283 3.293.369V21l4.184-4.183a1.14 1.14 0 0 1 .778-.332a48.294 48.294 0 0 0 5.83-.498c1.585-.233 2.708-1.626 2.708-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0 0 12 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018Z"
      />
    </svg>
  );
};

export const FilledLikeIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M4.41 12.961a2.5 2.5 0 0 0 1.076.244h5.346a2.5 2.5 0 0 0 2.47-2.114l.626-4.003a2 2 0 0 0-1.976-2.31H8.67V2.422a1.625 1.625 0 0 0-3.044-.794l-2.077 3.71a1.5 1.5 0 0 0-.191.733v5.442a1.5 1.5 0 0 0 .854 1.354l.2.095Zm-3.366-7.44a.996.996 0 0 0-.997.996v5.112a.997.997 0 0 0 .997.997h.496a.5.5 0 0 0 .5-.5V6.02a.5.5 0 0 0-.5-.5h-.496Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const StopGeneratingIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M1.5 0A1.5 1.5 0 0 0 0 1.5v11A1.5 1.5 0 0 0 1.5 14h11a1.5 1.5 0 0 0 1.5-1.5v-11A1.5 1.5 0 0 0 12.5 0z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const LikeFeedbackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M5.75 9.415H4.568c-.98 0-1.775.794-1.775 1.775v8.284c0 .98.795 1.776 1.775 1.776h1.184c.98 0 1.775-.795 1.775-1.776V11.19c0-.98-.795-1.775-1.775-1.775" />
        <path d="m21.16 12.243l-1.42 7.101a2.367 2.367 0 0 1-2.367 1.906h-7.48a2.367 2.367 0 0 1-2.367-2.367v-7.101A3.231 3.231 0 0 1 8.71 9.415l.982-5.918a.888.888 0 0 1 1.278-.65l1.1.544a3.55 3.55 0 0 1 1.87 4.047l-.496 1.965h5.396a2.367 2.367 0 0 1 2.32 2.84" />
      </g>
    </svg>
  );
};

export const CopyMessageIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M18.327 7.286h-8.044a1.932 1.932 0 0 0-1.925 1.938v10.088c0 1.07.862 1.938 1.925 1.938h8.044a1.932 1.932 0 0 0 1.925-1.938V9.224c0-1.07-.862-1.938-1.925-1.938" />
        <path d="M15.642 7.286V4.688c0-.514-.203-1.007-.564-1.37a1.918 1.918 0 0 0-1.361-.568H5.673c-.51 0-1 .204-1.36.568a1.945 1.945 0 0 0-.565 1.37v10.088c0 .514.203 1.007.564 1.37c.361.364.85.568 1.361.568h2.685" />
      </g>
    </svg>
  );
};

export const DislikeFeedbackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M5.75 2.75H4.568c-.98 0-1.775.795-1.775 1.776v8.284c0 .98.795 1.775 1.775 1.775h1.184c.98 0 1.775-.794 1.775-1.775V4.526c0-.98-.795-1.776-1.775-1.776" />
        <path d="m21.16 11.757l-1.42-7.101a2.368 2.368 0 0 0-2.367-1.906h-7.48a2.367 2.367 0 0 0-2.367 2.367v7.101a3.231 3.231 0 0 0 1.184 2.367l.982 5.918a.887.887 0 0 0 1.278.65l1.1-.543a3.551 3.551 0 0 0 1.87-4.048l-.496-1.965h5.396a2.368 2.368 0 0 0 2.32-2.84" />
      </g>
    </svg>
  );
};

export const ThumbsUpIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiThumbsUp size={size} className={className} />;
};

export const RobotIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FaRobot size={size} className={className} />;
};

export const SlackIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <g fill="none" stroke="currentColor">
        <path d="M5.5 2a.5.5 0 1 0 1 0a.5.5 0 1 0-1 0m6 4a.5.5 0 1 0 1 0a.5.5 0 1 0-1 0m-4 6a.5.5 0 1 0 1 0a.5.5 0 1 0-1 0m-6-4a.5.5 0 1 0 1 0a.5.5 0 1 0-1 0" />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M8.793 1.219v4.937m-3.59 1.692v4.937M1.215 5.207h4.937m1.692 3.59h4.937"
        />
      </g>
    </svg>
  );
};

export const SlackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M16.923 16.52h-2.39a1.984 1.984 0 0 1-1.973-1.195a2.006 2.006 0 0 1 .47-2.263a1.99 1.99 0 0 1 1.502-.53h4.858a1.978 1.978 0 0 1 1.969 1.63a1.951 1.951 0 0 1-1.147 2.173a2.21 2.21 0 0 1-.876.174c-.8.022-1.601.01-2.413.01m-9.435.501v-2.477a2.003 2.003 0 0 1 .56-1.402a1.987 1.987 0 0 1 1.377-.608a1.942 1.942 0 0 1 1.393.522c.377.352.6.84.62 1.357c.043 1.738.043 3.477 0 5.215A1.94 1.94 0 0 1 10.805 21a1.922 1.922 0 0 1-1.423.495a1.954 1.954 0 0 1-1.359-.614a1.97 1.97 0 0 1-.535-1.395c-.01-.815 0-1.64 0-2.466m8.938-9.963v2.434a1.996 1.996 0 0 1-.524 1.5a1.98 1.98 0 0 1-2.242.469a1.981 1.981 0 0 1-1.078-1.165a1.996 1.996 0 0 1-.106-.804V4.46a1.963 1.963 0 0 1 .605-1.386a1.947 1.947 0 0 1 1.408-.537a1.962 1.962 0 0 1 1.383.602a1.979 1.979 0 0 1 .553 1.408c.011.836 0 1.673 0 2.51M6.97 11.511H4.545a1.962 1.962 0 0 1-1.393-.579a1.978 1.978 0 0 1-.427-2.155a1.978 1.978 0 0 1 1.066-1.07a1.97 1.97 0 0 1 .754-.15h4.923a1.962 1.962 0 0 1 1.392.579a1.98 1.98 0 0 1-1.392 3.375zm4.478-6.171v.902c0 .18-.06.261-.216.261H9.165A1.916 1.916 0 0 1 7.9 5.787a1.929 1.929 0 0 1-.4-1.402c.022-.492.227-.958.574-1.306a1.965 1.965 0 0 1 3.342 1.12c.032.38.032.487.032.832v.214zm-5.009 7.204c.06.813.06 1.63 0 2.444a1.902 1.902 0 0 1-.754 1.18a1.887 1.887 0 0 1-1.356.34a1.988 1.988 0 0 1-1.293-.627a2.003 2.003 0 0 1-.536-1.338a1.96 1.96 0 0 1 .497-1.346c.33-.369.786-.599 1.278-.643c.736-.065 1.471-.01 2.164-.01M17.443 11.5V9.329c.052-.509.299-.977.689-1.305c.39-.329.891-.492 1.399-.455c.522 0 1.023.208 1.392.579a1.981 1.981 0 0 1 0 2.796c-.37.371-.87.58-1.392.58c-.671 0-1.363-.022-2.088-.022m-4.967 6.072c.8-.055 1.603-.055 2.402 0c.488.09.92.367 1.208.773c.286.406.405.908.329 1.4a1.99 1.99 0 0 1-.67 1.264a1.98 1.98 0 0 1-1.343.485a1.922 1.922 0 0 1-1.314-.528a1.937 1.937 0 0 1-.6-1.287c-.044-.695-.012-1.401-.012-2.107"
      />
    </svg>
  );
};

export const ToolIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M21.75 6.75a4.5 4.5 0 0 1-4.884 4.484c-1.076-.091-2.264.071-2.95.904l-7.152 8.684a2.548 2.548 0 1 1-3.586-3.586l8.684-7.152c.833-.686.995-1.874.904-2.95a4.5 4.5 0 0 1 6.336-4.486l-3.276 3.276a3.004 3.004 0 0 0 2.25 2.25l3.276-3.276c.256.565.398 1.192.398 1.852Z" />
        <path d="M4.867 19.125h.008v.008h-.008v-.008Z" />
      </g>
    </svg>
  );
};
export const ToolIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M12 6.75a5.25 5.25 0 0 1 6.775-5.025a.75.75 0 0 1 .313 1.248l-3.32 3.319a2.248 2.248 0 0 0 1.941 1.939l3.318-3.319a.75.75 0 0 1 1.248.313a5.25 5.25 0 0 1-5.472 6.756c-1.018-.086-1.87.1-2.309.634L7.344 21.3A3.298 3.298 0 1 1 2.7 16.657l8.684-7.151c.533-.44.72-1.291.634-2.309A5.342 5.342 0 0 1 12 6.75ZM4.117 19.125a.75.75 0 0 1 .75-.75h.008a.75.75 0 0 1 .75.75v.008a.75.75 0 0 1-.75.75h-.008a.75.75 0 0 1-.75-.75v-.008Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const CpuIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M8.25 3v1.5M4.5 8.25H3m18 0h-1.5M4.5 12H3m18 0h-1.5m-15 3.75H3m18 0h-1.5M8.25 19.5V21M12 3v1.5m0 15V21m3.75-18v1.5m0 15V21m-9-1.5h10.5a2.25 2.25 0 0 0 2.25-2.25V6.75a2.25 2.25 0 0 0-2.25-2.25H6.75A2.25 2.25 0 0 0 4.5 6.75v10.5a2.25 2.25 0 0 0 2.25 2.25Zm.75-12h9v9h-9v-9Z"
      />
    </svg>
  );
};
export const CpuIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g fill="currentColor">
        <path d="M16.5 7.5h-9v9h9v-9Z" />
        <path
          fillRule="evenodd"
          d="M8.25 2.25A.75.75 0 0 1 9 3v.75h2.25V3a.75.75 0 0 1 1.5 0v.75H15V3a.75.75 0 0 1 1.5 0v.75h.75a3 3 0 0 1 3 3v.75H21A.75.75 0 0 1 21 9h-.75v2.25H21a.75.75 0 0 1 0 1.5h-.75V15H21a.75.75 0 0 1 0 1.5h-.75v.75a3 3 0 0 1-3 3h-.75V21a.75.75 0 0 1-1.5 0v-.75h-2.25V21a.75.75 0 0 1-1.5 0v-.75H9V21a.75.75 0 0 1-1.5 0v-.75h-.75a3 3 0 0 1-3-3v-.75H3A.75.75 0 0 1 3 15h.75v-2.25H3a.75.75 0 0 1 0-1.5h.75V9H3a.75.75 0 0 1 0-1.5h.75v-.75a3 3 0 0 1 3-3h.75V3a.75.75 0 0 1 .75-.75ZM6 6.75A.75.75 0 0 1 6.75 6h10.5a.75.75 0 0 1 .75.75v10.5a.75.75 0 0 1-.75.75H6.75a.75.75 0 0 1-.75-.75V6.75Z"
          clipRule="evenodd"
        />
      </g>
    </svg>
  );
};

export const EmbeddingIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25m18 0A2.25 2.25 0 0 0 18.75 3H5.25A2.25 2.25 0 0 0 3 5.25m18 0V12a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 12V5.25"
      />
    </svg>
  );
};

export const EmbeddingIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M2.25 5.25a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3V15a3 3 0 0 1-3 3h-3v.257c0 .597.237 1.17.659 1.591l.621.622a.75.75 0 0 1-.53 1.28h-9a.75.75 0 0 1-.53-1.28l.621-.622a2.25 2.25 0 0 0 .659-1.59V18h-3a3 3 0 0 1-3-3V5.25Zm1.5 0v7.5a1.5 1.5 0 0 0 1.5 1.5h13.5a1.5 1.5 0 0 0 1.5-1.5v-7.5a1.5 1.5 0 0 0-1.5-1.5H5.25a1.5 1.5 0 0 0-1.5 1.5Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const PackageIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="m20.25 7.5l-.625 10.632a2.25 2.25 0 0 1-2.247 2.118H6.622a2.25 2.25 0 0 1-2.247-2.118L3.75 7.5M10 11.25h4M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125Z"
      />
    </svg>
  );
};
export const PackageIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 20 20"
    >
      <g fill="currentColor">
        <path d="M2 3a1 1 0 0 0-1 1v1a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1V4a1 1 0 0 0-1-1H2Z" />
        <path
          fillRule="evenodd"
          d="M2 7.5h16l-.811 7.71a2 2 0 0 1-1.99 1.79H4.802a2 2 0 0 1-1.99-1.79L2 7.5ZM7 11a1 1 0 0 1 1-1h4a1 1 0 1 1 0 2H8a1 1 0 0 1-1-1Z"
          clipRule="evenodd"
        />
      </g>
    </svg>
  );
};
export const UsersIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="12" cy="6" r="4" />
        <path
          strokeLinecap="round"
          d="M19.997 18c.003-.164.003-.331.003-.5c0-2.485-3.582-4.5-8-4.5s-8 2.015-8 4.5S4 22 12 22c2.231 0 3.84-.157 5-.437"
        />
      </g>
    </svg>
  );
};
export const UsersIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        d="M8 8a3 3 0 1 0 0-6a3 3 0 0 0 0 6m4.735 6c.618 0 1.093-.561.872-1.139a6.002 6.002 0 0 0-11.215 0c-.22.578.254 1.139.872 1.139z"
      />
    </svg>
  );
  // return <FiUser size={size} className={className} />;
};

export const GroupsIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1.5">
        <circle cx="9" cy="6" r="4" />
        <path strokeLinecap="round" d="M15 9a3 3 0 1 0 0-6" />
        <ellipse cx="9" cy="17" rx="7" ry="4" />
        <path
          strokeLinecap="round"
          d="M18 14c1.754.385 3 1.359 3 2.5c0 1.03-1.014 1.923-2.5 2.37"
        />
      </g>
    </svg>
  );
};
export const GroupsIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        d="M8.5 4.5a2.5 2.5 0 1 1-5 0a2.5 2.5 0 0 1 5 0m2.4 7.506c.11.542-.348.994-.9.994H2c-.553 0-1.01-.452-.902-.994a5.002 5.002 0 0 1 9.803 0M14.002 12h-1.59a2.556 2.556 0 0 0-.04-.29a6.476 6.476 0 0 0-1.167-2.603a3.002 3.002 0 0 1 3.633 1.911c.18.522-.283.982-.836.982M12 8a2 2 0 1 0 0-4a2 2 0 0 0 0 4"
      />
    </svg>
  );
};
export const KeyIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M15.75 5.25a3 3 0 0 1 3 3m3 0a6 6 0 0 1-7.029 5.912c-.563-.097-1.159.026-1.563.43L10.5 17.25H8.25v2.25H6v2.25H2.25v-2.818c0-.597.237-1.17.659-1.591l6.499-6.499c.404-.404.527-1 .43-1.563A6 6 0 1 1 21.75 8.25Z"
      />
    </svg>
  );
};
export const KeyIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 20 20"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M8 7a5 5 0 1 1 3.61 4.804l-1.903 1.903A1 1 0 0 1 9 14H8v1a1 1 0 0 1-1 1H6v1a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-2a1 1 0 0 1 .293-.707L8.196 8.39A5.002 5.002 0 0 1 8 7Zm5-3a.75.75 0 0 0 0 1.5A1.5 1.5 0 0 1 14.5 7A.75.75 0 0 0 16 7a3 3 0 0 0-3-3Z"
        clipRule="evenodd"
      />
    </svg>
  );
};
export const ShieldIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M9 12.75L11.25 15L15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6A11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623c5.176-1.332 9-6.03 9-11.622c0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z"
      />
    </svg>
  );
};
export const ShieldIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M8.5 1.709a.75.75 0 0 0-1 0a8.963 8.963 0 0 1-4.84 2.217a.75.75 0 0 0-.654.72a10.499 10.499 0 0 0 5.647 9.672a.75.75 0 0 0 .694-.001a10.499 10.499 0 0 0 5.647-9.672a.75.75 0 0 0-.654-.719A8.963 8.963 0 0 1 8.5 1.71m2.34 5.504a.75.75 0 0 0-1.18-.926L7.394 9.17l-1.156-.99a.75.75 0 1 0-.976 1.138l1.75 1.5a.75.75 0 0 0 1.078-.106z"
        clipRule="evenodd"
      />
    </svg>
  );
};
export const DatabaseIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1.5">
        <path strokeLinecap="round" d="M4 18V6m16 0v12" />
        <path d="M12 10c4.418 0 8-1.79 8-4s-3.582-4-8-4s-8 1.79-8 4s3.582 4 8 4Zm8 2c0 2.21-3.582 4-8 4s-8-1.79-8-4m16 6c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
      </g>
    </svg>
  );
};
export const DatabaseIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M.552 2.278c0-.155.077-.368.357-.63c.28-.262.722-.527 1.319-.762C3.418.416 5.105.112 7 .112c1.895 0 3.582.304 4.772.774c.597.235 1.038.5 1.32.762c.28.262.356.475.356.63c0 .155-.077.368-.357.63c-.28.261-.722.526-1.319.762c-1.19.47-2.877.774-4.772.774c-1.895 0-3.582-.304-4.772-.774c-.597-.236-1.038-.5-1.32-.763c-.28-.261-.356-.474-.356-.63Zm12.96 1.89a6.317 6.317 0 0 1-1.281.665c-1.37.54-3.22.86-5.231.86c-2.012 0-3.861-.32-5.231-.86a6.315 6.315 0 0 1-1.281-.666v3.178c.056.085.135.178.246.279c.29.263.745.53 1.36.766c1.224.471 2.959.776 4.906.776c1.947 0 3.682-.305 4.907-.776c.614-.237 1.069-.503 1.359-.766c.11-.101.19-.194.246-.28zM.488 11.208V8.993c.341.213.732.4 1.156.564c1.402.539 3.295.859 5.356.859c2.06 0 3.954-.32 5.356-.86a6.821 6.821 0 0 0 1.156-.563v2.216C13.512 12.749 10.597 14 7 14C3.403 14 .488 12.75.488 11.209Z"
        clipRule="evenodd"
      />
    </svg>
  );
};
export const SettingsIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g fill="none" stroke="currentColor" strokeWidth="1.5">
        <path strokeLinecap="round" d="M4 18V6m16 0v12" />
        <path d="M12 10c4.418 0 8-1.79 8-4s-3.582-4-8-4s-8 1.79-8 4s3.582 4 8 4Zm8 2c0 2.21-3.582 4-8 4s-8-1.79-8-4m16 6c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
      </g>
    </svg>
  );
};
export const SettingsIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="m21.51 14.59l-1.25-1.32a7.878 7.878 0 0 0-.06-2.9l1.22-1.32a.76.76 0 0 0 .14-.79a10.257 10.257 0 0 0-2.2-3.35a.74.74 0 0 0-.72-.19l-1.84.47a8.48 8.48 0 0 0-1.83-1l-.45-1.72a.73.73 0 0 0-.59-.55a9.92 9.92 0 0 0-1.89-.17a9.36 9.36 0 0 0-2.35.31a.73.73 0 0 0-.53.53l-.48 1.77a8.23 8.23 0 0 0-1.52.88l-1.82-.45a.73.73 0 0 0-.72.21a10 10 0 0 0-2.23 3.62a.76.76 0 0 0 .16.77l1.26 1.31a8.85 8.85 0 0 0-.1 1.27c0 .3 0 .6.05.9l-1.31 1.46a.75.75 0 0 0-.16.73a10 10 0 0 0 2 3.59a.75.75 0 0 0 .76.24l1.72-.44a7.918 7.918 0 0 0 2 1.23l.5 1.79a.77.77 0 0 0 .56.53c.721.163 1.459.247 2.2.25c.59-.006 1.178-.063 1.76-.17a.75.75 0 0 0 .59-.53l.47-1.69a8.109 8.109 0 0 0 2.38-1.34l1.76.4a.74.74 0 0 0 .73-.24a10.118 10.118 0 0 0 2-3.34a.76.76 0 0 0-.21-.75m-9.39 1.27a3.81 3.81 0 1 1-.021-7.619a3.81 3.81 0 0 1 .02 7.62"
      />
    </svg>
  );
};

export const PaintingIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M1.5 12h11a1 1 0 0 0 1-1V3a1 1 0 0 0-1-1h-11a1 1 0 0 0-1 1v8a1 1 0 0 0 1 1" />
        <path d="M9.502 6.212a1.245 1.245 0 1 0 0-2.49a1.245 1.245 0 0 0 0 2.49M9.083 12a7.098 7.098 0 0 0-7.136-5.786A7.6 7.6 0 0 0 .5 6.349" />
        <path d="M13.5 8.94a7.716 7.716 0 0 0-5.506.225" />
      </g>
    </svg>
  );
};

export const ImageIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
    >
      <path
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="2"
        d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
      />
    </svg>
  );
};

export const PaintingIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 36 36"
    >
      <path
        fill="currentColor"
        d="M32 4H4a2 2 0 0 0-2 2v24a2 2 0 0 0 2 2h28a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2ZM8.92 8a3 3 0 1 1-3 3a3 3 0 0 1 3-3ZM6 27v-4.1l6-6.08a1 1 0 0 1 1.41 0L16 19.35L8.32 27Zm24 0H11.15l6.23-6.23l5.4-5.4a1 1 0 0 1 1.41 0L30 21.18Z"
      />
      <path fill="none" d="M0 0h36v36H0z" />
    </svg>
  );
};

export const StarIconSkeleton = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="m14.92 8.797l-.624 1.86a4.75 4.75 0 0 1-3.029 3.03l-1.882.626a.316.316 0 0 0 0 .601l1.882.626a4.744 4.744 0 0 1 3.005 3.007l.625 1.883a.317.317 0 0 0 .6 0l.649-1.86a4.749 4.749 0 0 1 3.005-3.007l1.881-.625a.316.316 0 0 0 0-.601l-1.858-.65a4.744 4.744 0 0 1-3.028-3.03l-.625-1.884a.317.317 0 0 0-.6.024M6.859 3.516l-.446 1.329A3.392 3.392 0 0 1 4.25 7.01l-1.345.446a.226.226 0 0 0 0 .43l1.345.447a3.388 3.388 0 0 1 2.146 2.148l.446 1.345a.226.226 0 0 0 .43 0l.462-1.328A3.392 3.392 0 0 1 9.88 8.35l1.345-.447a.226.226 0 0 0 0-.43L9.897 7.01a3.388 3.388 0 0 1-2.163-2.165l-.446-1.346a.226.226 0 0 0-.43.017"
      />
    </svg>
  );
};

export const SwapIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      >
        <path d="M3.53 11.47v2.118a4.235 4.235 0 0 0 4.235 4.236H20.47M3.53 6.176h12.705a4.235 4.235 0 0 1 4.236 4.236v2.117" />
        <path d="m17.294 14.647l3.177 3.176L17.294 21M6.706 9.353L3.529 6.176L6.706 3" />
      </g>
    </svg>
  );
};

export const ClosedBookIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M12.5 13.54H3a1.5 1.5 0 0 1 0-3h8.5a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1H3A1.5 1.5 0 0 0 1.5 2v10m10-1.46v3"
      />
    </svg>
  );
};

export const PinIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="m17.942 6.076l2.442 2.442a1.22 1.22 0 0 1-.147 1.855l-1.757.232a1.697 1.697 0 0 0-.94.452c-.72.696-1.453 1.428-2.674 2.637c-.21.212-.358.478-.427.769l-.94 3.772a1.22 1.22 0 0 1-1.978.379l-3.04-3.052l-3.052-3.04a1.221 1.221 0 0 1 .379-1.978l3.747-.964a1.8 1.8 0 0 0 .77-.44c1.379-1.355 1.88-1.855 2.66-2.698c.233-.25.383-.565.428-.903l.232-1.783a1.221 1.221 0 0 1 1.856-.146zm-9.51 9.498L3.256 20.75"
      />
    </svg>
  );
};

export const TwoRightArrowIcons = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="m5.36 19l5.763-5.763a1.738 1.738 0 0 0 0-2.474L5.36 5m7 14l5.763-5.763a1.738 1.738 0 0 0 0-2.474L12.36 5"
      />
    </svg>
  );
};

export const PlusIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        d="M8.75 3.75a.75.75 0 0 0-1.5 0v3.5h-3.5a.75.75 0 0 0 0 1.5h3.5v3.5a.75.75 0 0 0 1.5 0v-3.5h3.5a.75.75 0 0 0 0-1.5h-3.5z"
      />
    </svg>
  );
};

export const MinusIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 16 16"
    >
      <path
        fill="currentColor"
        d="M3.75 7.25a.75.75 0 0 0 0 1.5h8.5a.75.75 0 0 0 0-1.5z"
      />
    </svg>
  );
};

export const CameraIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <g
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M13.5 5a1 1 0 0 0-1-1h-2L9 2H5L3.5 4h-2a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1z" />
        <path d="M7 9.75a2.25 2.25 0 1 0 0-4.5a2.25 2.25 0 0 0 0 4.5" />
      </g>
    </svg>
  );
};

export const MacIcon = ({
  size = 16,
  className = "my-auto flex flex-shrink-0 ",
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M6.5 4.5a2 2 0 0 1 2 2v2h-2a2 2 0 1 1 0-4Zm4 4v-2a4 4 0 1 0-4 4h2v3h-2a4 4 0 1 0 4 4v-2h3v2a4 4 0 1 0 4-4h-2v-3h2a4 4 0 1 0-4-4v2h-3Zm0 2h3v3h-3v-3Zm5-2v-2a2 2 0 1 1 2 2h-2Zm0 7h2a2 2 0 1 1-2 2v-2Zm-7 0v2a2 2 0 1 1-2-2h2Z"
      />
    </svg>
  );
};

export const DocumentIcon2 = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"
      />
    </svg>
  );
};

export const WindowsIcon = ({
  size = 16,
  className = "my-auto flex flex-shrink-0 ",
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      width="24"
      height="24"
    >
      <path
        fill="currentColor"
        d="M3 3h8v8H3V3zm10 0h8v8h-8V3zm-10 10h8v8H3v-8zm10 0h8v8h-8v-8z"
      />
    </svg>
  );
};

export const OpenIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M7 13.5a9.26 9.26 0 0 0-5.61-2.95a1 1 0 0 1-.89-1V1.5A1 1 0 0 1 1.64.51A9.3 9.3 0 0 1 7 3.43zm0 0a9.26 9.26 0 0 1 5.61-2.95a1 1 0 0 0 .89-1V1.5a1 1 0 0 0-1.14-.99A9.3 9.3 0 0 0 7 3.43z"
      />
    </svg>
  );
};

export const DexpandTwoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="m.5 13.5l5-5m-4 0h4v4m8-12l-5 5m4 0h-4v-4"
      />
    </svg>
  );
};

export const ExpandTwoIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="m8.5 5.5l5-5m-4 0h4v4m-8 4l-5 5m4 0h-4v-4"
      />
    </svg>
  );
};

export const DownloadCSVIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 14 14"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        d="M.5 10.5v1a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2v-1M4 6l3 3.5L10 6M7 9.5v-9"
      />
    </svg>
  );
};

export const UserIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M19.618 21.25c0-3.602-4.016-6.53-7.618-6.53c-3.602 0-7.618 2.928-7.618 6.53M12 11.456a4.353 4.353 0 1 0 0-8.706a4.353 4.353 0 0 0 0 8.706"
      />
    </svg>
  );
};

export const EgnyteIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={egnyteIcon} />;
};

export const AirtableIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={airtableIcon} />;
};

export const GitbookIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div className="flex items-center justify-center">
    <div className="dark:hidden">
      <LogoIcon size={size} className={className} src={gitbookDarkIcon} />
    </div>
    <div className="hidden dark:block">
      <LogoIcon size={size} className={className} src={gitbookLightIcon} />
    </div>
  </div>
);

export const HighspotIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <LogoIcon size={size} className={className} src={highspotIcon} />;
};

export const PinnedIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 14 14"
      fill="none"
    >
      <path
        d="M5.33165 8.74445L1 13M2.33282 5.46113L8.4591 11.4798L9.58999 10.3688L9.32809 7.88941L13 4.83L9.10152 1L5.98673 4.6074L3.46371 4.3501L2.33282 5.46113Z"
        stroke="currentColor"
        strokeWidth="1.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};
export const OnyxLogoTypeIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  const aspectRatio = 2640 / 733; // Calculate the aspect ratio of the original SVG
  const height = size / aspectRatio; // Calculate the height based on the aspect ratio

  return (
    <svg
      version="1.1"
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={height}
      viewBox="0 0 2640 733"
      style={{ width: `${size}px`, height: `${height}px` }}
      className={`w-[${size}px] h-[${height}px] ` + className}
    >
      <path
        d="M0 0 C33.33 0 66.66 0 101 0 C116.0557783 38.21851415 116.0557783 38.21851415 122.9375 56 C123.73628808 58.06186447 124.53511763 60.12371288 125.33398438 62.18554688 C132.03825266 79.49433582 138.7196772 96.811945 145.40026855 114.12988281 C154.13201714 136.7646467 162.89604763 159.38677068 171.67333984 182.00390625 C175.22064578 191.14500491 178.76491946 200.28727941 182.30947876 209.42944336 C184.28953371 214.53634164 186.26977615 219.64316721 188.25 224.75 C189.04166757 226.79166632 189.83333424 228.83333298 190.625 230.875 C191.2128125 232.3909375 191.2128125 232.3909375 191.8125 233.9375 C193 237 194.1875 240.0625 195.375 243.125 C195.96267654 244.6405825 195.96267654 244.6405825 196.56222534 246.18678284 C197.35481547 248.23083697 198.14739765 250.27489418 198.93997192 252.31895447 C200.90494473 257.38661809 202.8700505 262.45423006 204.83544922 267.52172852 C208.56750336 277.14472477 212.29807286 286.76829035 216.02435303 296.39352417 C217.79675153 300.97152352 219.56985562 305.54924943 221.34301758 310.12695312 C222.19314439 312.32229107 223.04292035 314.51776492 223.89233398 316.71337891 C225.06537285 319.74545515 226.2395878 322.77707344 227.4140625 325.80859375 C227.93916916 327.16729836 227.93916916 327.16729836 228.47488403 328.55345154 C228.79464203 329.37813431 229.11440002 330.20281708 229.44384766 331.05249023 C229.72185211 331.77073471 229.99985657 332.48897919 230.2862854 333.22898865 C230.99698266 335.06102535 230.99698266 335.06102535 232 337 C246.56988259 292.81493181 261.13820056 248.62935087 275.6875 204.4375 C275.96156803 203.60505013 276.23563606 202.77260025 276.51800919 201.91492462 C279.01707729 194.32423703 281.51604488 186.73351636 284.01490784 179.14276123 C289.17792065 163.45917323 294.3418852 147.77589867 299.50601101 132.09267712 C302.59609693 122.70820373 305.68610876 113.32370595 308.77612305 103.93920898 C309.06425106 103.06415274 309.35237907 102.18909649 309.64923823 101.28752339 C311.15291036 96.72081077 312.65658203 92.154098 314.16025352 87.58738518 C316.88233858 79.32030053 319.60442781 71.05321725 322.32651675 62.78613389 C323.81240457 58.27343827 325.29829211 53.76074257 326.78417969 49.24804688 C327.37414551 47.45629883 327.96411133 45.66455078 328.55407715 43.87280273 C328.84746979 42.98175842 329.14086243 42.09071411 329.44314575 41.17266846 C333.96209717 27.44844564 338.48104858 13.72422282 343 0 C367.99937294 -0.58538238 392.99771191 -1.02550978 418.00257015 -1.2953043 C429.6146466 -1.42393963 441.22245313 -1.59910139 452.83178711 -1.88598633 C462.95725523 -2.13608217 473.07963139 -2.29665662 483.20810229 -2.35221237 C488.56749218 -2.38467268 493.91804247 -2.46022203 499.27458 -2.64325142 C532.79129476 -3.74490236 532.79129476 -3.74490236 540.42525101 2.4351387 C546.11597516 7.94072522 549.54345055 14.7896396 552.64213753 22.00372505 C554.56104941 26.23801807 557.12001289 29.84116876 559.875 33.5625 C560.74382604 34.81477537 561.60901068 36.06959387 562.46875 37.328125 C563.09330078 38.23401367 563.09330078 38.23401367 563.73046875 39.15820312 C565.94759045 42.37473507 568.16143251 45.59352145 570.375 48.8125 C571.04861572 49.79198608 571.04861572 49.79198608 571.73583984 50.79125977 C575.88812976 56.8318215 580.02612448 62.88212951 584.16357422 68.93286133 C587.60197218 73.96013108 591.04732974 78.98252305 594.5 84 C598.50958746 89.82679816 602.50756794 95.66143452 606.5 101.5 C618.66861604 119.30630862 618.66861604 119.30630862 631 137 C633.93322556 134.22886427 636.18623177 131.43481587 638.37109375 128.046875 C639.0165918 127.05220215 639.66208984 126.0575293 640.32714844 125.03271484 C641.37177246 123.407771 641.37177246 123.407771 642.4375 121.75 C643.18594341 120.594188 643.93498196 119.43876119 644.68457031 118.28369141 C645.87691047 116.4461905 647.06885448 114.60844385 648.25906372 112.76956177 C652.45578077 106.28625376 656.69365977 99.83021026 660.93508911 93.37609863 C662.7114261 90.67277816 664.48642899 87.96858282 666.26145935 85.2644043 C667.61103107 83.20841458 668.96077303 81.15253671 670.31054688 79.09667969 C672.96271903 75.05695522 675.61427434 71.01682617 678.265625 66.9765625 C678.69839752 66.31709122 679.13117004 65.65761993 679.57705688 64.97816467 C681.74925116 61.66806158 683.92132765 58.35788126 686.09326172 55.04760742 C690.15895391 48.85129621 694.22565727 42.65565607 698.29595947 36.46237183 C700.1986006 33.5672177 702.10066371 30.67168405 704.00268555 27.77612305 C704.90132401 26.4084212 705.80023926 25.04090117 706.69946289 23.67358398 C707.95401163 21.76593684 709.20756431 19.8576384 710.4609375 17.94921875 C711.55293981 16.28790204 712.64697455 14.62713955 713.79142761 13.00151062 C715.12629684 10.93344915 715.12629684 10.93344915 716.04707336 8.15730286 C717.64187545 4.52163394 718.9067278 2.5270255 722 0 C729.20177109 -2.08840248 737.15310869 -1.27358726 744.55859375 -1.07421875 C746.79057478 -1.05369084 749.02260553 -1.0380382 751.25465393 -1.02705383 C757.11679012 -0.98514255 762.97590648 -0.87717399 768.83685303 -0.75531006 C774.82246038 -0.64258465 780.808558 -0.59250224 786.79492188 -0.53710938 C798.53127155 -0.41929536 810.26538425 -0.23167118 822 0 C820.553704 3.75941534 818.91642122 6.80235597 816.5859375 10.09765625 C815.91151611 11.05768555 815.23709473 12.01771484 814.54223633 13.00683594 C813.82704834 14.01520508 813.11186035 15.02357422 812.375 16.0625 C810.9067251 18.15176282 809.43926664 20.24159965 807.97265625 22.33203125 C807.27543457 23.32412598 806.57821289 24.3162207 805.85986328 25.33837891 C803.18180282 29.17090911 800.59870181 33.0586811 798.0234375 36.9609375 C795.36316557 40.95648105 792.65120576 44.91561926 789.9375 48.875 C789.38537842 49.6805835 788.83325684 50.48616699 788.2644043 51.31616211 C787.41616089 52.55378296 787.41616089 52.55378296 786.55078125 53.81640625 C782.9003326 59.14263677 779.26155213 64.47677492 775.625 69.8125 C774.68829468 71.18668091 774.68829468 71.18668091 773.73266602 72.58862305 C771.82164232 75.39232337 769.91079192 78.19614172 768 81 C760.31372146 92.27869313 752.62415374 103.55504107 744.91357422 114.81713867 C740.76838789 120.87310547 736.63288078 126.93563003 732.5 133 C727.8399646 139.83788867 723.17469524 146.67212488 718.5 153.5 C713.24267506 161.1793747 707.99177778 168.86311662 702.75732422 176.55810547 C699.43988066 181.43315548 696.10700963 186.29662341 692.75 191.14453125 C691.71431885 192.64632935 691.71431885 192.64632935 690.65771484 194.1784668 C689.32948516 196.10380959 687.99666621 198.02599664 686.65869141 199.94458008 C686.06233887 200.81107178 685.46598633 201.67756348 684.8515625 202.5703125 C684.05999756 203.71137451 684.05999756 203.71137451 683.25244141 204.87548828 C681.95654959 207.07370477 681.15461584 208.44868613 681 211 C682.21715668 213.50960961 682.21715668 213.50960961 684.16796875 216.109375 C684.91224121 217.17607422 685.65651367 218.24277344 686.42333984 219.34179688 C686.83807556 219.92791748 687.25281128 220.51403809 687.68011475 221.11791992 C690.08556959 224.54795949 692.40329624 228.03742521 694.73828125 231.515625 C695.80171139 233.09175087 696.86569251 234.66750512 697.93017578 236.24291992 C698.48030334 237.05731537 699.03043091 237.87171082 699.597229 238.71078491 C700.44628815 239.96769638 700.44628815 239.96769638 701.3125 241.25 C702.50508189 243.01600738 703.69762671 244.78203979 704.89013672 246.5480957 C707.36330739 250.21070426 709.83663631 253.87320589 712.31005859 257.53564453 C715.83911575 262.76143727 719.36703433 267.98799773 722.89453125 273.21484375 C734.27251271 290.07392081 745.65406902 306.93057002 757.0425415 323.78256226 C765.76190859 336.68512283 774.4756335 349.59148371 783.18685913 362.49954224 C789.4720778 371.81275642 795.75900144 381.1248105 802.05078125 390.43359375 C802.62283295 391.2799942 803.19488464 392.12639465 803.78427124 392.9984436 C806.50812915 397.0285268 809.23231545 401.0583874 811.95703125 405.08789062 C813.83882414 407.87084107 815.7184406 410.65523891 817.59619141 413.44091797 C819.06398292 415.61794403 820.54021307 417.78797899 822.02490234 419.95361328 C822.57742676 420.76427246 823.12995117 421.57493164 823.69921875 422.41015625 C824.15514404 423.07281494 824.61106934 423.73547363 825.08081055 424.41821289 C826 426 826 426 826 428 C812.7186023 428.55849244 799.44003393 428.98365536 786.14924622 429.24349213 C779.97546122 429.36828224 773.80975625 429.5371114 767.640625 429.81054688 C724.95337975 431.65373323 724.95337975 431.65373323 716.75460434 424.41446114 C712.04037734 419.35447539 709.3798801 413.28122189 707.07299805 406.84484863 C705.66007111 403.09874371 703.78648606 400.42885338 701.359375 397.2578125 C700.75101807 396.39043457 700.14266113 395.52305664 699.51586914 394.62939453 C698.93313232 393.80294434 698.35039551 392.97649414 697.75 392.125 C692.61911083 384.79623086 687.57133526 377.42388622 682.63208008 369.96484375 C678.44807504 363.6523053 674.20014438 357.38466408 669.9375 351.125 C669.22142578 350.073125 668.50535156 349.02125 667.76757812 347.9375 C666.27717369 345.74859181 664.78664067 343.55977184 663.29589844 341.37109375 C650.09138869 321.98362059 636.97651467 302.54099407 624 283 C620.63667007 286.25172952 618.2102807 289.63210501 615.8125 293.625 C611.27686126 301.02497708 606.57303832 308.30539272 601.8125 315.5625 C601.07558406 316.68651154 600.33868638 317.81053504 599.60180664 318.93457031 C598.4901004 320.62998761 597.37820842 322.32528213 596.2658844 324.02029419 C592.58359576 329.63180255 588.91534424 335.25241454 585.25 340.875 C584.63568115 341.81714355 584.0213623 342.75928711 583.38842773 343.72998047 C577.781703 352.33079027 572.18575556 360.93858921 566.59277344 369.54833984 C564.98145814 372.02854037 563.36971782 374.50846414 561.7578125 376.98828125 C561.22019287 377.81537598 560.68257324 378.6424707 560.12866211 379.49462891 C559.04623436 381.15972763 557.96371539 382.82476707 556.88110352 384.48974609 C554.13288848 388.7166856 551.38679308 392.94497671 548.64453125 397.17578125 C543.54752725 405.03601526 538.4393602 412.88782053 533.25 420.6875 C532.83145752 421.31760986 532.41291504 421.94771973 531.98168945 422.59692383 C529.12379488 426.87620512 529.12379488 426.87620512 528 428 C524.8949275 428.09533653 521.81213542 428.12551126 518.70678711 428.11352539 C517.73128403 428.11367142 516.75578094 428.11381744 515.75071716 428.1139679 C512.50957047 428.11326833 509.26848046 428.10547391 506.02734375 428.09765625 C503.78674857 428.09579222 501.54615298 428.09436825 499.30555725 428.09336853 C493.3954049 428.08954213 487.48527695 428.0797108 481.57513428 428.06866455 C475.54944183 428.05845306 469.52374547 428.05387147 463.49804688 428.04882812 C451.66535384 428.03808864 439.83267894 428.02101076 428 428 C429.38759602 424.40646837 430.89676703 421.46843574 433.1328125 418.32421875 C433.76622559 417.42566162 434.39963867 416.52710449 435.05224609 415.60131836 C435.73625488 414.6397583 436.42026367 413.67819824 437.125 412.6875 C442.99768374 404.34860964 448.74795589 395.9440765 454.375 387.4375 C459.22154648 380.12019918 464.15866216 372.91643864 469.3125 365.8125 C473.01095468 360.63466345 476.4858559 355.30363446 480 350 C484.97233364 342.4956293 490.02639754 335.09874934 495.3125 327.8125 C499.01095468 322.63466345 502.4858559 317.30363446 506 312 C510.97233364 304.4956293 516.02639754 297.09874934 521.3125 289.8125 C525.01095468 284.63466345 528.4858559 279.30363446 532 274 C536.96973115 266.49955704 542.02030355 259.1059207 547.3046875 251.82421875 C551.75049226 245.60043968 555.91137952 239.17416483 560.1171875 232.78710938 C560.76171875 231.81193359 561.40625 230.83675781 562.0703125 229.83203125 C562.70614258 228.86990723 563.34197266 227.9077832 563.99707031 226.91650391 C566.71903045 222.95300613 569.65142849 219.15949055 572.62451172 215.3815918 C574.17664131 213.1750609 574.17664131 213.1750609 573.94384766 211.0390625 C572.66324387 208.27248134 571.07159907 205.87694269 569.34375 203.36328125 C568.7827359 202.54166252 568.7827359 202.54166252 568.21038818 201.70344543 C566.97900566 199.90268667 565.73951427 198.10766881 564.5 196.3125 C563.63580164 195.05167482 562.77220246 193.79043875 561.90917969 192.52880859 C560.13808681 189.94102732 558.36412106 187.35525348 556.58789062 184.77099609 C552.78670296 179.23720439 549.02026713 173.6798895 545.25 168.125 C537.51068925 156.74271199 529.75657459 145.37052708 522 134 C513.43731085 121.4477725 504.88308804 108.88986605 496.34082031 96.32373047 C489.2374038 85.87553272 482.11978682 75.43704638 475 65 C472.54146006 61.3959742 470.08312899 57.7918061 467.625 54.1875 C466.71524414 52.85380371 466.71524414 52.85380371 465.78710938 51.49316406 C462.33719761 46.43389556 458.89251854 41.37111171 455.453125 36.3046875 C454.68278621 35.17032452 453.91244119 34.03596578 453.14208984 32.90161133 C451.66751494 30.73020867 450.19405483 28.55806342 448.72119141 26.38549805 C445.20779569 21.21120144 441.66428168 16.06868536 438 11 C435.08364827 18.08863373 432.46200954 25.24489145 429.98046875 32.49609375 C429.60532639 33.58542709 429.23018402 34.67476044 428.84367371 35.79710388 C428.04037885 38.13038493 427.23816706 40.46403908 426.43695068 42.79803467 C424.3028893 49.01424033 422.16062809 55.22762113 420.01953125 61.44140625 C419.58991089 62.68893677 419.16029053 63.93646729 418.71765137 65.22180176 C414.96449345 76.11593334 411.17746429 86.99799684 407.375 97.875 C402.06285691 113.07626901 396.77421708 128.28553048 391.5 143.5 C386.28337043 158.54605188 381.05918969 173.58940169 375.8125 188.625 C375.51695221 189.4720047 375.22140442 190.3190094 374.91690063 191.19168091 C371.55933516 200.81292478 368.19842817 210.43299977 364.83585358 220.05249405 C362.28588913 227.3473167 359.73645342 234.64232401 357.1875 241.9375 C356.95257339 242.60984428 356.71764679 243.28218857 356.4756012 243.97490692 C349.06020798 265.19824903 341.68382863 286.43477977 334.33886719 307.68261719 C329.1266949 322.75869322 323.8879652 337.82528061 318.62036133 352.88208008 C315.27876751 362.43837041 311.96295893 372.00296953 308.67578125 381.578125 C286.91538109 444.91097327 286.91538109 444.91097327 276 463 C275.62584961 463.62052246 275.25169922 464.24104492 274.86621094 464.88037109 C264.62809287 481.55301222 251.42718504 495.89386772 237.94189453 509.96533203 C234.91302457 513.13890536 231.92528159 516.35029604 228.9375 519.5625 C224.13395104 524.71676262 219.32059266 529.86167518 214.5 535 C209.06399618 540.79503813 203.63494056 546.5964599 198.21679688 552.40820312 C195.22343867 555.61901301 192.22641742 558.82626083 189.22265625 562.02734375 C188.5994751 562.69241943 187.97629395 563.35749512 187.33422852 564.04272461 C186.15490895 565.30115732 184.974497 566.55856768 183.79272461 567.81469727 C183.25268799 568.39147217 182.71265137 568.96824707 182.15625 569.5625 C181.69025391 570.05878906 181.22425781 570.55507813 180.74414062 571.06640625 C179.01041791 572.88440751 179.01041791 572.88440751 177.90902519 574.69213963 C175.8242579 577.65667667 174.21232765 579.67328349 170.63210678 580.63813591 C167.68494552 580.86195595 164.80898166 580.86588305 161.85400391 580.79467773 C160.7412207 580.79569992 159.6284375 580.79672211 158.48193359 580.79777527 C154.81249657 580.79290759 151.14556352 580.73849841 147.4765625 580.68359375 C144.92924356 580.67053481 142.38190702 580.66057204 139.83456421 580.65357971 C133.82063293 580.62960552 127.80777254 580.57446934 121.79426992 580.50413328 C114.27317501 580.41808165 106.75193337 580.3798694 99.23046875 580.34179688 C85.81961581 580.27370262 72.41071531 580.13347157 59 580 C59 550.3 59 520.6 59 490 C102.6875 489.625 102.6875 489.625 116.40893555 489.52197266 C120.51884962 489.48199967 120.51884962 489.48199967 124.6287384 489.43954468 C126.43897042 489.42202512 128.2492402 489.40814891 130.05952454 489.39730835 C149.0629029 489.27840054 166.5526309 489.00809099 181 475 C194.03833167 460.33187687 198.69268726 438.59464263 204.69360352 420.32080078 C205.61021258 417.53517626 206.53373079 414.75186488 207.45752525 411.96861649 C209.36609119 406.21746858 211.26957235 400.46460988 213.16162109 394.70800781 C213.4935849 393.69925598 213.82554871 392.69050415 214.16757202 391.65118408 C214.85646855 389.4571306 215.44224984 387.23100064 216 385 C194.88 385 173.76 385 152 385 C141.07422789 357.73568794 130.22141622 330.44397546 119.42333984 303.12890625 C115.84670474 294.08207047 112.26544029 285.03706728 108.68447876 275.99194336 C106.70612518 270.9947057 104.72807827 265.99734665 102.75 261 C101.9583348 258.99999942 101.16666813 256.99999942 100.375 255 C79 201 79 201 57.625 147 C57.23311493 146.00997482 56.84122986 145.01994965 56.43746948 143.99992371 C55.64590381 142.00017831 54.85433887 140.00043262 54.06277466 138.00068665 C52.08206882 132.99678884 50.1013502 127.99289609 48.12060547 122.98901367 C44.57655061 114.03576268 41.03256326 105.08248502 37.48910522 96.1289978 C36.31684935 93.16703084 35.14450913 90.20509727 33.97216797 87.24316406 C32.41610715 83.31168029 30.86049218 79.38002051 29.30517578 75.44824219 C25.18391305 65.03169504 21.05482122 54.61830871 16.91510391 44.20908165 C15.209152 39.91857313 13.50497312 35.62735984 11.80047607 31.33627319 C10.855479 28.95880946 9.90956649 26.58170939 8.96270752 24.20498657 C7.64735757 20.90317604 6.33508189 17.60015896 5.0234375 14.296875 C4.62960876 13.31069687 4.23578003 12.32451874 3.83001709 11.30845642 C3.47022766 10.40067947 3.11043823 9.49290253 2.73974609 8.55761719 C2.42621185 7.76973816 2.11267761 6.98185913 1.78964233 6.17010498 C1 4 1 4 0 0 Z "
        fill="currentColor"
        transform="translate(1814,153)"
      />
      <path
        d="M0 0 C0.83810211 -0.00701431 1.67620422 -0.01402863 2.53970337 -0.02125549 C5.23095126 -0.03866647 7.92197909 -0.04510809 10.61328125 -0.046875 C11.53273529 -0.04754974 12.45218933 -0.04822449 13.39950562 -0.04891968 C27.10769148 -0.03292448 40.46897884 0.34679399 53.92578125 3.203125 C54.75158691 3.37473145 55.57739258 3.54633789 56.42822266 3.72314453 C104.10137996 13.9446933 148.92015889 40.48134523 178.92578125 79.203125 C179.34972168 79.74533691 179.77366211 80.28754883 180.21044922 80.84619141 C214.41902295 124.87863761 228.47978789 178.81199691 222.328125 234.04736328 C216.03894851 283.37618327 192.43364033 325.71878914 158.61669922 361.41503906 C156.70289786 363.4388163 154.80039938 365.47290577 152.8984375 367.5078125 C151.4911795 369.01069209 150.08362987 370.51329867 148.67578125 372.015625 C148.02633545 372.70906006 147.37688965 373.40249512 146.70776367 374.11694336 C142.79169615 378.27866642 138.80498502 382.35314517 134.73291016 386.36254883 C132.92273746 388.20622512 131.22818343 390.1135503 129.55078125 392.078125 C126.80956676 395.26995009 123.91892237 398.24615477 120.92578125 401.203125 C117.99459934 404.09904458 115.16174951 407.00555071 112.48828125 410.140625 C108.70337756 414.57591787 104.54438343 418.61510611 100.37890625 422.6875 C97.94357318 424.99986008 97.94357318 424.99986008 96.62890625 427.31640625 C93.86386929 430.37950912 90.26049646 431.30794193 86.42578125 432.640625 C85.58136475 432.9406543 84.73694824 433.24068359 83.86694336 433.54980469 C62.3934153 441.0136629 40.93860537 444.75407348 18.19897461 444.59423828 C15.49216208 444.57814807 12.7868463 444.59421089 10.08007812 444.61328125 C-6.01970762 444.63290793 -21.99241242 442.8557798 -37.63671875 438.953125 C-38.9196582 438.63734497 -38.9196582 438.63734497 -40.22851562 438.31518555 C-73.32229062 429.88088614 -103.90200102 413.51357452 -128.91796875 390.20703125 C-130.92123799 388.34529733 -132.97995172 386.5858134 -135.07421875 384.828125 C-154.24034916 368.0002625 -168.35310867 345.10704354 -179.07421875 322.203125 C-179.59628906 321.11128906 -180.11835937 320.01945312 -180.65625 318.89453125 C-202.21048168 271.52071861 -202.79727805 213.17787182 -185.1484375 164.46484375 C-173.82008821 134.91287097 -155.84930804 107.17499298 -133.02246094 85.15234375 C-131.20497442 83.33394621 -129.53527624 81.46208081 -127.87109375 79.50390625 C-123.31051112 74.2512437 -118.35061936 69.42985833 -113.390625 64.55859375 C-110.00540165 61.21009977 -106.70976617 57.84651831 -103.60546875 54.234375 C-98.95475676 48.82891889 -93.82732379 43.910037 -88.74609375 38.9140625 C-83.96514754 34.18190146 -79.43948442 29.32013896 -75.07421875 24.203125 C-58.15046977 4.62939398 -24.77048816 0.13949758 0 0 Z M-81.671875 121.2109375 C-94.10751856 136.69988541 -102.42216287 153.91873058 -107.07421875 173.203125 C-107.39390625 174.45867187 -107.71359375 175.71421875 -108.04296875 177.0078125 C-112.75673366 198.0535558 -112.41571877 224.33468929 -107.07421875 245.203125 C-106.88617676 246.00073242 -106.69813477 246.79833984 -106.50439453 247.62011719 C-100.71613874 271.9059255 -89.23935154 293.26409368 -73.07421875 312.203125 C-72.04748047 313.41355469 -72.04748047 313.41355469 -71 314.6484375 C-47.9494122 341.05108564 -16.13936948 358.84287521 19.16259766 361.36279297 C46.59081946 362.79636518 74.17716739 354.47585384 94.92578125 336.203125 C95.74433594 335.52765625 96.56289062 334.8521875 97.40625 334.15625 C122.65186519 312.70726221 135.23054033 279.47024623 137.92578125 247.203125 C140.27625709 205.810847 128.67037622 165.12304253 100.8671875 133.6796875 C97.94939935 130.45922612 94.94396318 127.329408 91.92578125 124.203125 C91.04019531 123.22279297 91.04019531 123.22279297 90.13671875 122.22265625 C68.61718618 98.99259674 35.0082485 85.21932478 4.04296875 82.9140625 C-29.14695206 82.12553306 -59.95156963 96.35755729 -81.671875 121.2109375 Z "
        fill="currentColor"
        transform="translate(1161.07421875,144.796875)"
      />
      <path
        d="M0 0 C0.74490189 -0.00988449 1.48980377 -0.01976898 2.25727844 -0.029953 C50.02685431 -0.53245128 90.51113055 12.36122444 125.65625 45.61328125 C146.70645987 67.4971628 159.37409264 96.78597762 165.71875 126.11328125 C165.91766846 127.02053955 166.11658691 127.92779785 166.3215332 128.86254883 C170.15662585 147.76819 170.25182679 166.81619532 170.19580078 186.02832031 C170.1941145 188.77015288 170.195468 191.51198208 170.19668579 194.2538147 C170.19772564 200.1150116 170.19154441 205.97616338 170.18021011 211.83734894 C170.16383422 220.31123842 170.15873487 228.78510646 170.15623413 237.25901005 C170.1518758 251.01318047 170.13861771 264.76732693 170.11962891 278.52148438 C170.10122157 291.86848838 170.08708894 305.21548584 170.07861328 318.5625 C170.07808783 319.3876303 170.07756239 320.2127606 170.07702102 321.06289485 C170.07441061 325.20305393 170.07188327 329.34321306 170.06939721 333.48337221 C170.0487228 367.7350298 170.01188474 401.98664275 169.96875 436.23828125 C140.59875 436.23828125 111.22875 436.23828125 80.96875 436.23828125 C80.95416748 428.65384033 80.93958496 421.06939941 80.92456055 413.25512695 C80.87567801 388.91549748 80.8122347 364.5759265 80.73976372 340.23635652 C80.72849718 336.4480173 80.71735847 332.65967772 80.70629883 328.87133789 C80.7029933 327.74017644 80.7029933 327.74017644 80.699621 326.58616325 C80.66436498 314.41742491 80.6394351 302.24868662 80.61840298 290.07991634 C80.59654727 277.56940716 80.56340542 265.05896355 80.52004844 252.54851025 C80.49369883 244.84508894 80.47588106 237.14174914 80.46940396 229.43828508 C80.46346619 223.5053007 80.44173435 217.57243578 80.41447449 211.6395092 C80.4057624 209.22466949 80.4019573 206.80980564 80.40374184 204.39495087 C80.4208244 170.57795098 75.59013237 132.77364554 50.84375 107.36328125 C34.74804984 91.64278331 13.31965625 84.3749888 -8.90625 83.86328125 C-34.71741699 84.44989868 -58.6296742 92.74617622 -77.03125 111.23828125 C-97.237198 132.83991951 -104.16021891 163.32200101 -104.18946838 192.12161255 C-104.19440636 193.17146265 -104.19934434 194.22131275 -104.20443195 195.30297649 C-104.21970325 198.7958956 -104.22813927 202.28879648 -104.23657227 205.78173828 C-104.24615895 208.29549823 -104.25616949 210.8092566 -104.26657104 213.32301331 C-104.28796255 218.72218414 -104.30642312 224.12135215 -104.32217598 229.52054214 C-104.34495666 237.32671637 -104.37308777 245.13286423 -104.40249526 252.93901597 C-104.45007113 265.60614219 -104.49336218 278.27327924 -104.53393555 290.94042969 C-104.57334155 303.24024294 -104.61477987 315.54004659 -104.65893555 327.83984375 C-104.66165982 328.59890039 -104.66438409 329.35795702 -104.66719092 330.14001538 C-104.68087124 333.94824732 -104.69459134 337.75647912 -104.70833123 341.56471086 C-104.82213871 373.12254876 -104.928189 404.68040597 -105.03125 436.23828125 C-134.73125 436.23828125 -164.43125 436.23828125 -195.03125 436.23828125 C-195.03125 294.99828125 -195.03125 153.75828125 -195.03125 8.23828125 C-165.33125 8.23828125 -135.63125 8.23828125 -105.03125 8.23828125 C-104.70125 27.37828125 -104.37125 46.51828125 -104.03125 66.23828125 C-100.56625 62.27828125 -100.56625 62.27828125 -97.03125 58.23828125 C-95.71682638 56.88630267 -94.3877664 55.54802123 -93.03125 54.23828125 C-90.43142817 51.67837991 -87.96856602 49.07048585 -85.59375 46.30078125 C-83.02459729 43.31026409 -80.33807744 40.50711441 -77.53125 37.73828125 C-74.12798063 34.381002 -70.9630553 30.91038954 -67.85546875 27.28125 C-65.09061865 24.1848547 -62.12088088 21.30582671 -59.14453125 18.4140625 C-56.95404037 16.28178654 -56.95404037 16.28178654 -55.265625 13.66015625 C-52.22091621 10.35994742 -49.19424393 9.4613871 -44.96875 8.17578125 C-43.7923999 7.80126831 -43.7923999 7.80126831 -42.59228516 7.41918945 C-28.8051804 3.17101218 -14.455506 0.15855111 0 0 Z "
        fill="currentColor"
        transform="translate(1630.03125,144.76171875)"
      />
      <path
        d="M0 0 C2.38143646 0.95204965 4.66474801 1.93938584 6.9765625 3.03515625 C7.64632111 3.34503983 8.31607971 3.6549234 9.00613403 3.97419739 C10.45502737 4.64529835 11.90244088 5.31960167 13.34851074 5.99676514 C17.28525304 7.83974485 21.23314298 9.65859946 25.1796875 11.48046875 C25.99570435 11.85790222 26.81172119 12.23533569 27.65246582 12.62420654 C35.24684457 16.13041351 42.88818173 19.52557216 50.54144287 22.90084839 C64.74910513 29.16757199 78.87098464 35.60271852 92.95608521 42.1399231 C105.56993927 47.99156219 118.24093862 53.69850855 130.96044922 59.31640625 C141.80271707 64.10701193 152.57447648 69.02171692 163.30908203 74.05004883 C176.83057762 80.36079749 190.48865925 86.36485514 204.13589478 92.39733887 C209.77491735 94.89295962 215.39430951 97.4303158 221 100 C218.28771101 103.3023264 214.68401289 104.73818118 210.87890625 106.44921875 C210.15992157 106.77874039 209.44093689 107.10826202 208.70016479 107.44776917 C206.32395617 108.53442542 203.94335827 109.61107376 201.5625 110.6875 C199.8937747 111.44783214 198.22523897 112.20858047 196.55688477 112.96972656 C184.46077963 118.47742824 172.31861067 123.88115312 160.16287231 129.25570679 C149.25806702 134.07726202 138.42334852 139.02302429 127.62548828 144.08056641 C118.40661512 148.38323273 109.11928332 152.51689675 99.8125 156.625 C85.61505373 162.89310403 71.51530598 169.35473837 57.44631958 175.90567017 C43.06084311 182.6030892 28.62983404 189.18383697 14.11132812 195.58837891 C11.89012859 196.59614536 9.68730279 197.64481766 7.49804688 198.72021484 C6.34884766 199.28047363 5.19964844 199.84073242 4.015625 200.41796875 C2.98211914 200.93512451 1.94861328 201.45228027 0.88378906 201.98510742 C-4.62279823 203.92304201 -8.86034932 201.32394333 -13.87890625 198.96484375 C-14.5500798 198.65496017 -15.22125336 198.3450766 -15.9127655 198.02580261 C-17.36723373 197.35384474 -18.82063255 196.6795683 -20.27307129 196.00323486 C-24.22484546 194.16367398 -28.18489354 192.34208919 -32.14453125 190.51953125 C-33.37319412 189.95338104 -33.37319412 189.95338104 -34.62667847 189.37579346 C-42.23342215 185.87754887 -49.88260613 182.47916104 -57.54244995 179.09915161 C-71.74878884 172.83015312 -85.87122674 166.39716911 -99.95608521 159.8600769 C-112.56993927 154.00843781 -125.24093862 148.30149145 -137.96044922 142.68359375 C-148.80271707 137.89298807 -159.57447648 132.97828308 -170.30908203 127.94995117 C-183.83057762 121.63920251 -197.48865925 115.63514486 -211.13589478 109.60266113 C-216.77491735 107.10704038 -222.39430951 104.5696842 -228 102 C-228 101.34 -228 100.68 -228 100 C-208.96990129 91.17964828 -189.93885123 82.36818675 -170.78076172 73.82861328 C-161.47189338 69.67450975 -152.20210363 65.43917651 -142.9375 61.1875 C-131.07933174 55.74614873 -119.18362405 50.39867978 -107.25 45.125 C-93.78985391 39.17645246 -80.41172146 33.06564376 -67.0640564 26.86914062 C-53.2803913 20.47294082 -39.42766418 14.24567147 -25.51953125 8.125 C-24.451689 7.65401886 -24.451689 7.65401886 -23.36227417 7.17352295 C-22.00264694 6.57412276 -20.64226143 5.97643894 -19.28103638 5.38067627 C-15.88988516 3.88548315 -12.61399874 2.28385617 -9.37109375 0.4921875 C-5.40397836 -1.26382418 -4.14424383 -1.00602452 0 0 Z "
        fill="currentColor"
        transform="translate(370,530)"
      />
      <path
        d="M0 0 C0.66 0 1.32 0 2 0 C2.49177734 1.08901611 2.98355469 2.17803223 3.49023438 3.30004883 C5.82583784 8.47131121 8.16271888 13.64199569 10.5 18.8125 C11.1440831 20.23746796 11.1440831 20.23746796 11.80117798 21.69122314 C17.56255614 34.43493377 23.35557963 47.16343967 29.1875 59.875 C34.84426524 72.20531301 40.38209701 84.58434871 45.86605835 96.99237061 C51.491098 109.7096263 57.28584746 122.34285838 63.1399231 134.95608521 C68.98729551 147.56074197 74.69461887 160.22071051 80.30331421 172.93325806 C83.73255225 180.70451144 87.18470715 188.46070308 90.78125 196.15625 C91.08258347 196.80116898 91.38391693 197.44608795 91.69438171 198.11054993 C93.09709069 201.10689714 94.50811603 204.09885205 95.92895508 207.08666992 C96.89529608 209.13646028 97.84393722 211.19473257 98.77075195 213.26269531 C99.53558928 214.96584448 100.340312 216.65232793 101.20385742 218.30761719 C102.82112021 221.85443625 103.25171734 224.02496081 102.2644043 227.84936523 C100.89490649 231.28525401 99.33501246 234.56337031 97.6875 237.875 C97.08394375 239.14365358 96.48351527 240.41379921 95.88598633 241.68530273 C94.6079002 244.39657917 93.31518067 247.1001516 92.01171875 249.79931641 C88.97291652 256.11391361 86.08523772 262.49773801 83.18356323 268.87615967 C82.17658153 271.08646584 81.16519854 273.29470891 80.15258789 275.50244141 C75.39486895 285.8826618 70.74044648 296.30586887 66.125 306.75 C60.17346804 320.2168991 54.05840043 333.6011398 47.8600769 346.95608521 C42.01090383 359.56462351 36.30648975 372.23032779 30.69064331 384.94433594 C25.73533892 396.1584162 20.66458506 407.30938882 15.46435547 418.41210938 C13.01949874 423.63461434 10.60006476 428.86378165 8.265625 434.13671875 C7.84788818 435.07966797 7.43015137 436.02261719 6.99975586 436.99414062 C6.2317571 438.73639073 5.46917521 440.48104306 4.71313477 442.22851562 C2.21791802 447.89104099 2.21791802 447.89104099 0 449 C-0.49177734 447.91098389 -0.98355469 446.82196777 -1.49023438 445.69995117 C-3.82583784 440.52868879 -6.16271888 435.35800431 -8.5 430.1875 C-9.1440831 428.76253204 -9.1440831 428.76253204 -9.80117798 427.30877686 C-15.56255614 414.56506623 -21.35557963 401.83656033 -27.1875 389.125 C-32.84426524 376.79468699 -38.38209701 364.41565129 -43.86605835 352.00762939 C-49.491098 339.2903737 -55.28584746 326.65714162 -61.1399231 314.04391479 C-66.98706511 301.43975468 -72.69064335 288.77890485 -78.30331421 276.0687561 C-83.86081736 263.48797197 -89.5903795 250.99709236 -95.42578125 238.54296875 C-95.87518066 237.57149902 -96.32458008 236.6000293 -96.78759766 235.59912109 C-97.52203805 234.02464417 -98.27253158 232.45733968 -99.05224609 230.90478516 C-101.06073153 226.74847773 -101.058315 224.44564743 -100 220 C-98.9051726 217.32807666 -97.76859972 214.74954149 -96.52734375 212.1484375 C-96.17302277 211.38980408 -95.81870178 210.63117065 -95.4536438 209.84954834 C-94.68832412 208.21224451 -93.91982052 206.57642592 -93.14846802 204.94195557 C-91.07013421 200.536397 -89.01636484 196.11940553 -86.9609375 191.703125 C-86.54068802 190.80147614 -86.12043854 189.89982727 -85.68745422 188.97085571 C-81.70296337 180.4032542 -77.86973 171.77244911 -74.0625 163.125 C-67.89901873 149.14644535 -61.53024284 135.27083115 -55.08288574 121.42114258 C-49.55431376 109.54347648 -44.10418211 97.63853569 -38.77392578 85.67041016 C-34.6402172 76.39728479 -30.42243936 67.16472421 -26.1875 57.9375 C-19.69862154 43.79766493 -13.34130735 29.60226131 -7.05151367 15.37280273 C-6.56479942 14.27269363 -6.56479942 14.27269363 -6.06825256 13.15036011 C-5.46374124 11.78344765 -4.86011273 10.41614428 -4.2575531 9.04837036 C-2.90739365 5.99434024 -1.53001919 2.9685345 0 0 Z "
        fill="currentColor"
        transform="translate(630,142)"
      />
      <path
        d="M0 0 C1.13596367 0.53154945 1.13596367 0.53154945 2.2948761 1.07383728 C3.92670528 1.8383391 5.55663215 2.60691215 7.18481445 3.37915039 C11.57252393 5.45952627 15.97461317 7.50911219 20.375 9.5625 C21.27314423 9.98254303 22.17128845 10.40258606 23.09664917 10.83535767 C31.6971507 14.84948123 40.36487536 18.70248537 49.05078125 22.52734375 C62.43733488 28.43202972 75.73694697 34.50823224 89.00796509 40.66781616 C101.62145533 46.51926381 114.29209559 52.22601825 127.01123047 57.84375 C137.84988029 62.63275707 148.61877392 67.54432958 159.34887695 72.57299805 C170.87702047 77.95536258 182.50845376 83.10132797 194.1484375 88.23632812 C195.26818466 88.73107132 195.26818466 88.73107132 196.41055298 89.23580933 C197.80543467 89.85186781 199.20088087 90.46665049 200.59701538 91.0798645 C204.47199906 92.79105126 208.27717754 94.60307504 212.05078125 96.52734375 C209.59313167 99.35932021 207.05995942 100.60773538 203.64453125 102.1015625 C202.5268335 102.59567627 201.40913574 103.08979004 200.25756836 103.59887695 C199.65637177 103.86092926 199.05517517 104.12298157 198.4357605 104.39297485 C195.14623395 105.82723974 191.8669883 107.28475893 188.5859375 108.73828125 C187.89133926 109.04520401 187.19674103 109.35212677 186.48109436 109.66835022 C179.34665426 112.82575529 172.25712358 116.078926 165.1685791 119.33773804 C152.58690391 125.12051151 139.96611591 130.8053081 127.30078125 136.40234375 C113.83388215 142.35387571 100.44964145 148.46894332 87.09469604 154.66726685 C74.48659661 160.51623633 61.82221311 166.22268356 49.10745239 171.83569336 C40.21719767 175.76149695 31.35526206 179.73409599 22.55737305 183.86328125 C20.21016739 184.95764843 17.85494954 186.03502065 15.49145508 187.09375 C10.51434084 189.33336075 5.85003191 191.54497084 1.3671875 194.671875 C-3.30730917 197.72084874 -7.25844068 199.72627585 -12.94921875 199.52734375 C-23.91430744 196.67263963 -33.99692197 191.14492923 -44.03320312 186.00878906 C-51.25110541 182.33103456 -58.63040917 179.00552317 -66.00054932 175.64694214 C-68.46494274 174.52015431 -70.92435712 173.38316395 -73.38232422 172.24243164 C-84.14816407 167.24638345 -94.96523227 162.37963223 -105.82421875 157.58984375 C-119.8016631 151.42376281 -133.67832456 145.05761594 -147.52807617 138.61022949 C-159.38552399 133.0910683 -171.27090755 127.65184616 -183.21728516 122.32763672 C-192.30244078 118.2755355 -201.36266404 114.17084064 -210.41143799 110.03817749 C-211.95754069 109.33209836 -213.50388028 108.62653771 -215.05047607 107.92153931 C-229.86361928 101.16739681 -229.86361928 101.16739681 -236.94921875 97.52734375 C-235.40297635 94.43485896 -232.39497667 93.77224326 -229.34765625 92.46484375 C-228.65664825 92.16175293 -227.96564026 91.85866211 -227.25369263 91.54638672 C-225.74393793 90.88455358 -224.2329626 90.22549976 -222.72094727 89.56884766 C-218.60037978 87.77824555 -214.48968429 85.96528311 -210.37890625 84.15234375 C-209.52000793 83.77392334 -208.66110962 83.39550293 -207.77618408 83.00561523 C-198.61515962 78.9581325 -189.53116958 74.74850321 -180.44921875 70.52734375 C-167.01842822 64.29113497 -153.53427189 58.19365562 -139.98876953 52.2109375 C-129.12430747 47.41052541 -118.33093631 42.48485397 -107.57421875 37.4465332 C-97.61688065 32.79925504 -87.5769861 28.35132497 -77.52438354 23.91497803 C-62.64355788 17.34143391 -47.88025245 10.52383118 -33.13793945 3.64599609 C-32.29394592 3.25265076 -31.44995239 2.85930542 -30.5803833 2.45404053 C-29.00215581 1.71812923 -27.42451866 0.98095001 -25.84759521 0.24224854 C-24.47254039 -0.39926056 -23.09459654 -1.03463223 -21.71316528 -1.66229248 C-20.25193276 -2.33358828 -18.81033767 -3.04744289 -17.37475586 -3.77197266 C-11.1460286 -5.57131309 -5.51697816 -2.65206409 0 0 Z "
        fill="currentColor"
        transform="translate(378.94921875,4.47265625)"
      />
      <path
        d="M0 0 C3.16996538 2.64292957 4.58615167 5.99846112 6.23046875 9.68359375 C6.53747711 10.35750656 6.84448547 11.03141937 7.16079712 11.72575378 C8.17637287 13.96004264 9.18196727 16.19867546 10.1875 18.4375 C10.9047181 20.02088535 11.62241858 21.60405227 12.34057617 23.18701172 C17.557798 34.70815066 22.67921543 46.2717554 27.79125977 57.83984375 C33.68037773 71.1576613 39.77125553 84.37649769 45.91656494 97.57775879 C51.44532587 109.45578979 56.8956508 121.36108914 62.22607422 133.32958984 C66.02968777 141.86221489 69.90147058 150.36145132 73.79812622 158.85189819 C79.85693235 172.05571719 85.84366894 185.28973626 91.75 198.5625 C92.08842926 199.32144562 92.42685852 200.08039124 92.77554321 200.86233521 C93.10460663 201.60071625 93.43367004 202.33909729 93.77270508 203.09985352 C94.09215591 203.81593277 94.41160675 204.53201202 94.74073792 205.26979065 C95.35400396 206.65889757 95.95876734 208.05179432 96.55430603 209.44859314 C97.7667374 212.29076343 98.99862324 214.99771075 100.59277344 217.6484375 C102.08152337 220.2828054 102.78334997 221.96992389 103 225 C101.30365246 230.98647292 98.55822083 236.34364945 95.75 241.875 C94.95333102 243.50968153 94.16075039 245.14636126 93.37207031 246.78491211 C92.14947833 249.32297049 90.92414575 251.85931053 89.68548584 254.38957214 C85.82877172 262.27058347 82.25905167 270.2638989 78.74108887 278.30059814 C73.29272578 290.73506591 67.67777702 303.08043961 61.91943359 315.37451172 C57.61676727 324.59338488 53.48310325 333.88071668 49.375 343.1875 C43.49553804 356.50466014 37.45637596 369.74030384 31.3125 382.9375 C25.72169773 394.94841853 20.15935153 406.96859091 14.75 419.0625 C13.96882813 420.80793091 13.96882813 420.80793091 13.171875 422.58862305 C10.99165126 427.47731698 8.8303365 432.37253116 6.72265625 437.29296875 C6.22717285 438.44623657 6.22717285 438.44623657 5.72167969 439.62280273 C4.89684505 441.55265885 4.0825803 443.48702409 3.26953125 445.421875 C2 448 2 448 0 449 C-7.04441853 434.01047326 -13.93744829 418.96464382 -20.625 403.8125 C-26.50431543 390.49528108 -32.5434519 377.25960921 -38.6875 364.0625 C-44.62674464 351.30464185 -50.50063799 338.5258406 -56.22607422 325.67041016 C-60.35978255 316.39728534 -64.57752914 307.16470924 -68.8125 297.9375 C-75.12666444 284.17885184 -81.31788127 270.36887768 -87.42114258 256.51538086 C-87.73030106 255.81563644 -88.03945953 255.11589203 -88.35798645 254.39494324 C-88.9687589 253.01216297 -89.57766625 251.62855725 -90.18461609 250.24409485 C-91.79991779 246.58830932 -93.48746332 242.98697332 -95.28125 239.41503906 C-95.65664917 238.65667755 -96.03204834 237.89831604 -96.41882324 237.11697388 C-97.13902339 235.67054754 -97.87361421 234.23116094 -98.62512207 232.80075073 C-100.93690087 228.13205351 -101.37203683 225.20640287 -100 220 C-99.02397272 217.48373378 -98.01543578 215.10715429 -96.859375 212.6796875 C-96.54119812 211.99202301 -96.22302124 211.30435852 -95.89520264 210.59585571 C-94.85494485 208.35168255 -93.8023705 206.11351491 -92.75 203.875 C-91.6452649 201.49798118 -90.54383244 199.11944845 -89.44238281 196.74090576 C-88.69802847 195.13432195 -87.952581 193.52824417 -87.20605469 191.92266846 C-83.90135901 184.81214026 -80.68880328 177.66331233 -77.5 170.5 C-72.45966554 159.20686063 -67.32682016 147.95859258 -62.16937256 136.71862793 C-57.07024954 125.59897477 -52.0696608 114.4390986 -47.125 103.25 C-41.17615106 89.78917193 -35.06527632 76.41023562 -28.86813354 63.06204224 C-22.49936999 49.33854294 -16.29910784 35.54638709 -10.21289062 21.6953125 C-6.98775083 14.36937414 -3.69282015 7.10586496 0 0 Z "
        fill="currentColor"
        transform="translate(101,142)"
      />
    </svg>
  );
};

export const OnyxIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 56 56"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M27.9998 0L10.8691 7.76944L27.9998 15.5389L45.1305 7.76944L27.9998 0ZM27.9998 40.4611L10.8691 48.2306L27.9998 56L45.1305 48.2306L27.9998 40.4611ZM48.2309 10.8691L56.0001 28.0003L48.2309 45.1314L40.4617 28.0003L48.2309 10.8691ZM15.5385 28.0001L7.76923 10.869L0 28.0001L7.76923 45.1313L15.5385 28.0001Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const QuestionMarkIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
};

export const NewChatIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 20 20"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M12.5 1.99982H6C3.79086 1.99982 2 3.79068 2 5.99982V13.9998C2 16.209 3.79086 17.9998 6 17.9998H14C16.2091 17.9998 18 16.209 18 13.9998V8.49982"
        stroke="currentColor"
        strokeLinecap="round"
      />
      <path
        d="M17.1471 5.13076C17.4492 4.82871 17.6189 4.41901 17.619 3.9918C17.6191 3.56458 17.4494 3.15484 17.1474 2.85271C16.8453 2.55058 16.4356 2.38082 16.0084 2.38077C15.5812 2.38071 15.1715 2.55037 14.8693 2.85242L11.0562 6.66651L7.24297 10.4806C7.1103 10.6129 7.01218 10.7758 6.95726 10.9549L6.20239 13.4418C6.18762 13.4912 6.18651 13.5437 6.19916 13.5937C6.21182 13.6437 6.23778 13.6894 6.27428 13.7258C6.31078 13.7623 6.35646 13.7881 6.40648 13.8007C6.45651 13.8133 6.509 13.8121 6.5584 13.7972L9.04585 13.0429C9.2248 12.9885 9.38766 12.891 9.52014 12.7589L17.1471 5.13076Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const Caret = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="m12.37 15.835l6.43-6.63C19.201 8.79 18.958 8 18.43 8H5.57c-.528 0-.771.79-.37 1.205l6.43 6.63c.213.22.527.22.74 0Z"
      />
    </svg>
  );
};

export const OpenAISVG = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 50 50"
    >
      <path
        fill="currentColor"
        d="M45.403,25.562c-0.506-1.89-1.518-3.553-2.906-4.862c1.134-2.665,0.963-5.724-0.487-8.237	c-1.391-2.408-3.636-4.131-6.322-4.851c-1.891-0.506-3.839-0.462-5.669,0.088C28.276,5.382,25.562,4,22.647,4	c-4.906,0-9.021,3.416-10.116,7.991c-0.01,0.001-0.019-0.003-0.029-0.002c-2.902,0.36-5.404,2.019-6.865,4.549	c-1.391,2.408-1.76,5.214-1.04,7.9c0.507,1.891,1.519,3.556,2.909,4.865c-1.134,2.666-0.97,5.714,0.484,8.234	c1.391,2.408,3.636,4.131,6.322,4.851c0.896,0.24,1.807,0.359,2.711,0.359c1.003,0,1.995-0.161,2.957-0.45	C21.722,44.619,24.425,46,27.353,46c4.911,0,9.028-3.422,10.12-8.003c2.88-0.35,5.431-2.006,6.891-4.535	C45.754,31.054,46.123,28.248,45.403,25.562z M35.17,9.543c2.171,0.581,3.984,1.974,5.107,3.919c1.049,1.817,1.243,4,0.569,5.967	c-0.099-0.062-0.193-0.131-0.294-0.19l-9.169-5.294c-0.312-0.179-0.698-0.177-1.01,0.006l-10.198,6.041l-0.052-4.607l8.663-5.001	C30.733,9.26,33,8.963,35.17,9.543z M29.737,22.195l0.062,5.504l-4.736,2.805l-4.799-2.699l-0.062-5.504l4.736-2.805L29.737,22.195z M14.235,14.412C14.235,9.773,18.009,6,22.647,6c2.109,0,4.092,0.916,5.458,2.488C28,8.544,27.891,8.591,27.787,8.651l-9.17,5.294	c-0.312,0.181-0.504,0.517-0.5,0.877l0.133,11.851l-4.015-2.258V14.412z M6.528,23.921c-0.581-2.17-0.282-4.438,0.841-6.383	c1.06-1.836,2.823-3.074,4.884-3.474c-0.004,0.116-0.018,0.23-0.018,0.348V25c0,0.361,0.195,0.694,0.51,0.872l10.329,5.81	L19.11,34.03l-8.662-5.002C8.502,27.905,7.11,26.092,6.528,23.921z M14.83,40.457c-2.171-0.581-3.984-1.974-5.107-3.919	c-1.053-1.824-1.249-4.001-0.573-5.97c0.101,0.063,0.196,0.133,0.299,0.193l9.169,5.294c0.154,0.089,0.327,0.134,0.5,0.134	c0.177,0,0.353-0.047,0.51-0.14l10.198-6.041l0.052,4.607l-8.663,5.001C19.269,40.741,17.001,41.04,14.83,40.457z M35.765,35.588	c0,4.639-3.773,8.412-8.412,8.412c-2.119,0-4.094-0.919-5.459-2.494c0.105-0.056,0.216-0.098,0.32-0.158l9.17-5.294	c0.312-0.181,0.504-0.517,0.5-0.877L31.75,23.327l4.015,2.258V35.588z M42.631,32.462c-1.056,1.83-2.84,3.086-4.884,3.483	c0.004-0.12,0.018-0.237,0.018-0.357V25c0-0.361-0.195-0.694-0.51-0.872l-10.329-5.81l3.964-2.348l8.662,5.002	c1.946,1.123,3.338,2.937,3.92,5.107C44.053,28.249,43.754,30.517,42.631,32.462z"
      />
    </svg>
  );
};

export const SourcesIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 28 29"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path d="M6 22.5L14 14.5L22 6.5V14.5H14V22.5H6Z" fill="black" />
    </svg>
  );
};

export const WebSearchIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect
        x="0.65"
        y="0.65"
        width="22.7"
        height="22.7"
        rx="11.35"
        stroke="black"
        strokeWidth="1.3"
      />
      <path
        d="M9.24406 10.8918H10.8918V9.24406L8.96945 7.32174C9.58439 7.02805 10.2753 6.93222 10.9469 7.04746C11.6186 7.1627 12.238 7.48333 12.7199 7.96521C13.2017 8.44708 13.5224 9.0665 13.6376 9.73816C13.7528 10.4098 13.657 11.1007 13.3633 11.7156L16.6587 15.011C16.8772 15.2295 17 15.5259 17 15.8349C17 16.1439 16.8772 16.4402 16.6587 16.6587C16.4402 16.8772 16.1439 17 15.8349 17C15.5259 17 15.2295 16.8772 15.011 16.6587L11.7156 13.3633C11.1007 13.657 10.4098 13.7528 9.73816 13.6376C9.0665 13.5224 8.44708 13.2017 7.96521 12.7199C7.48333 12.238 7.1627 11.6186 7.04746 10.9469C6.93222 10.2753 7.02805 9.58439 7.32174 8.96945L9.24406 10.8918Z"
        stroke="black"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

export const ArtAsistantIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M12 1.5C9.98656 1.4999 8.01555 2.07871 6.32185 3.16743C4.62815 4.25616 3.28318 5.8089 2.44724 7.6406C1.6113 9.47231 1.31963 11.5057 1.60699 13.4986C1.89435 15.4914 2.74862 17.3596 4.068 18.8805L10.422 12.6285C10.8429 12.2144 11.4096 11.9824 12 11.9824C12.5904 11.9824 13.1571 12.2144 13.578 12.6285L19.932 18.8805C21.2514 17.3596 22.1056 15.4914 22.393 13.4986C22.6804 11.5057 22.3887 9.47231 21.5528 7.6406C20.7168 5.8089 19.3719 4.25616 17.6782 3.16743C15.9845 2.07871 14.0134 1.4999 12 1.5ZM12 22.5C14.5238 22.5042 16.9639 21.5952 18.87 19.941L12.525 13.6965C12.3848 13.5591 12.1963 13.4821 12 13.4821C11.8037 13.4821 11.6152 13.5591 11.475 13.6965L5.13 19.941C7.03607 21.5952 9.47619 22.5042 12 22.5ZM0 12C0 8.8174 1.26428 5.76516 3.51472 3.51472C5.76516 1.26428 8.8174 0 12 0C15.1826 0 18.2348 1.26428 20.4853 3.51472C22.7357 5.76516 24 8.8174 24 12C24 15.1826 22.7357 18.2348 20.4853 20.4853C18.2348 22.7357 15.1826 24 12 24C8.8174 24 5.76516 22.7357 3.51472 20.4853C1.26428 18.2348 0 15.1826 0 12ZM16.5 8.25C16.5 8.05109 16.421 7.86032 16.2803 7.71967C16.1397 7.57902 15.9489 7.5 15.75 7.5C15.5511 7.5 15.3603 7.57902 15.2197 7.71967C15.079 7.86032 15 8.05109 15 8.25C15 8.44891 15.079 8.63968 15.2197 8.78033C15.3603 8.92098 15.5511 9 15.75 9C15.9489 9 16.1397 8.92098 16.2803 8.78033C16.421 8.63968 16.5 8.44891 16.5 8.25ZM18 8.25C18 8.54547 17.9418 8.83806 17.8287 9.11104C17.7157 9.38402 17.5499 9.63206 17.341 9.84099C17.1321 10.0499 16.884 10.2157 16.611 10.3287C16.3381 10.4418 16.0455 10.5 15.75 10.5C15.4545 10.5 15.1619 10.4418 14.889 10.3287C14.616 10.2157 14.3679 10.0499 14.159 9.84099C13.9501 9.63206 13.7843 9.38402 13.6713 9.11104C13.5582 8.83806 13.5 8.54547 13.5 8.25C13.5 7.65326 13.7371 7.08097 14.159 6.65901C14.581 6.23705 15.1533 6 15.75 6C16.3467 6 16.919 6.23705 17.341 6.65901C17.7629 7.08097 18 7.65326 18 8.25Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const GeneralAssistantIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect
        x="0.65"
        y="0.65"
        width="22.7"
        height="22.7"
        rx="11.35"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M8.06264 10.3125C8.06253 9.66355 8.22283 9.02463 8.52926 8.45258C8.83569 7.88054 9.27876 7.3931 9.81906 7.03363C10.3594 6.67415 10.9801 6.4538 11.6261 6.39216C12.2722 6.33052 12.9234 6.42951 13.5219 6.68032C14.1204 6.93113 14.6477 7.32598 15.0568 7.82976C15.4659 8.33353 15.7441 8.93061 15.8667 9.56787C15.9893 10.2051 15.9525 10.8628 15.7596 11.4824C15.5667 12.102 15.2236 12.6644 14.7609 13.1194C14.5438 13.3331 14.3525 13.611 14.2603 13.9474L13.8721 15.375H10.1281L9.73889 13.9474C9.64847 13.6321 9.47612 13.3464 9.23939 13.1194C8.86681 12.753 8.57088 12.3161 8.36885 11.8342C8.16682 11.3523 8.06272 10.835 8.06264 10.3125ZM10.4364 16.5H13.5639L13.3715 17.211C13.3389 17.3301 13.2681 17.4351 13.1699 17.5099C13.0717 17.5847 12.9516 17.6252 12.8281 17.625H11.1721C11.0487 17.6252 10.9286 17.5847 10.8304 17.5099C10.7322 17.4351 10.6614 17.3301 10.6288 17.211L10.4364 16.5ZM12.0001 5.25C10.9954 5.25017 10.0134 5.5493 9.17925 6.10932C8.34506 6.66934 7.69637 7.46491 7.31577 8.39477C6.93516 9.32463 6.83985 10.3467 7.04197 11.3309C7.24409 12.3151 7.7345 13.2169 8.45076 13.9215C8.54562 14.0093 8.61549 14.1207 8.65326 14.2444L9.54426 17.5069C9.64173 17.8639 9.85387 18.179 10.148 18.4037C10.4422 18.6283 10.802 18.75 11.1721 18.75H12.8281C13.1983 18.75 13.5581 18.6283 13.8523 18.4037C14.1464 18.179 14.3585 17.8639 14.456 17.5069L15.3459 14.2444C15.384 14.1206 15.4542 14.0092 15.5495 13.9215C16.2658 13.2169 16.7562 12.3151 16.9583 11.3309C17.1604 10.3467 17.0651 9.32463 16.6845 8.39477C16.3039 7.46491 15.6552 6.66934 14.821 6.10932C13.9868 5.5493 13.0049 5.25017 12.0001 5.25Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const SearchAssistantIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <rect
        x="0.65"
        y="0.65"
        width="22.7"
        height="22.7"
        rx="11.35"
        stroke="currentColor"
        strokeWidth="1.3"
      />
      <path
        d="M17.0667 18L12.8667 13.8C12.5333 14.0667 12.15 14.2778 11.7167 14.4333C11.2833 14.5889 10.8222 14.6667 10.3333 14.6667C9.12222 14.6667 8.09733 14.2471 7.25867 13.408C6.42 12.5689 6.00044 11.544 6 10.3333C5.99956 9.12267 6.41911 8.09778 7.25867 7.25867C8.09822 6.41956 9.12311 6 10.3333 6C11.5436 6 12.5687 6.41956 13.4087 7.25867C14.2487 8.09778 14.668 9.12267 14.6667 10.3333C14.6667 10.8222 14.5889 11.2833 14.4333 11.7167C14.2778 12.15 14.0667 12.5333 13.8 12.8667L18 17.0667L17.0667 18ZM10.3333 13.3333C11.1667 13.3333 11.8751 13.0418 12.4587 12.4587C13.0422 11.8756 13.3338 11.1671 13.3333 10.3333C13.3329 9.49956 13.0413 8.79133 12.4587 8.20867C11.876 7.626 11.1676 7.33422 10.3333 7.33333C9.49911 7.33244 8.79089 7.62422 8.20867 8.20867C7.62644 8.79311 7.33467 9.50133 7.33333 10.3333C7.332 11.1653 7.62378 11.8738 8.20867 12.4587C8.79356 13.0436 9.50178 13.3351 10.3333 13.3333Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const SortIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        fill="currentColor"
        fillRule="evenodd"
        d="M17 3.25a.75.75 0 0 1 .75.75v13.75l1.65-2.2a.75.75 0 1 1 1.2.9l-3 4a.75.75 0 0 1-1.35-.45V4a.75.75 0 0 1 .75-.75ZM7.25 6A.75.75 0 0 1 8 5.25h5a.75.75 0 0 1 0 1.5H8A.75.75 0 0 1 7.25 6Zm-2 5a.75.75 0 0 1 .75-.75h7a.75.75 0 0 1 0 1.5H6a.75.75 0 0 1-.75-.75Zm-2 5a.75.75 0 0 1 .75-.75h9a.75.75 0 0 1 0 1.5H4a.75.75 0 0 1-.75-.75Z"
        clipRule="evenodd"
      />
    </svg>
  );
};

export const CirclingArrowIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      fill="currentColor"
      version="1.1"
      id="Capa_1"
      xmlns="http://www.w3.org/2000/svg"
      xmlnsXlink="http://www.w3.org/1999/xlink"
      width="800px"
      height="800px"
      viewBox="0 0 94.073 94.072"
      xmlSpace="preserve"
    >
      <g>
        <g>
          <path
            d="M91.465,5.491c-0.748-0.311-1.609-0.139-2.18,0.434l-8.316,8.316C72.046,5.057,60.125,0,47.399,0
			c-2.692,0-5.407,0.235-8.068,0.697C21.218,3.845,6.542,17.405,1.944,35.244c-0.155,0.599-0.023,1.235,0.355,1.724
			c0.379,0.489,0.962,0.775,1.581,0.775h12.738c0.839,0,1.59-0.524,1.878-1.313c3.729-10.193,12.992-17.971,23.598-19.814
			c1.747-0.303,3.525-0.456,5.288-0.456c8.428,0,16.299,3.374,22.168,9.5l-8.445,8.444c-0.571,0.572-0.742,1.432-0.434,2.179
			c0.311,0.748,1.039,1.235,1.848,1.235h28.181c1.104,0,2-0.896,2-2V7.338C92.7,6.53,92.211,5.801,91.465,5.491z"
          />
          <path
            d="M90.192,56.328H77.455c-0.839,0-1.59,0.523-1.878,1.312c-3.729,10.193-12.992,17.972-23.598,19.814
			c-1.748,0.303-3.525,0.456-5.288,0.456c-8.428,0-16.3-3.374-22.168-9.5l8.444-8.444c0.572-0.572,0.743-1.432,0.434-2.179
			c-0.31-0.748-1.039-1.235-1.848-1.235H3.374c-1.104,0-2,0.896-2,2v28.181c0,0.809,0.487,1.538,1.235,1.848
			c0.746,0.31,1.607,0.138,2.179-0.435l8.316-8.315c8.922,9.183,20.843,14.241,33.569,14.241c2.693,0,5.408-0.235,8.069-0.697
			c18.112-3.146,32.789-16.708,37.387-34.547c0.155-0.6,0.023-1.234-0.354-1.725C91.395,56.615,90.811,56.328,90.192,56.328z"
          />
        </g>
      </g>
    </svg>
  );
};

export const KnowledgeGroupIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
        d="M21.25 9.883v7.698a3.083 3.083 0 0 1-3.083 3.083H5.833a3.083 3.083 0 0 1-3.083-3.083V6.419a3.083 3.083 0 0 1 3.083-3.083h3.084a3.083 3.083 0 0 1 2.57 1.377l.873 1.326a1.748 1.748 0 0 0 1.449.77h4.358a3.084 3.084 0 0 1 3.083 3.074"
      />
    </svg>
  );
};

export const FileOptionIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M20.6801 7.02928C20.458 6.5654 20.1451 6.15072 19.76 5.80973L16.76 3.09074C16.0939 2.47491 15.2435 2.09552 14.3401 2.01115C14.2776 1.99628 14.2125 1.99628 14.15 2.01115H8.21008C7.54764 1.98307 6.88617 2.08698 6.26428 2.31683C5.64239 2.54667 5.07249 2.89785 4.58765 3.34995C4.10281 3.80205 3.71274 4.34605 3.44019 4.95025C3.16763 5.55445 3.01797 6.20679 3 6.86934V17.1655C3.03538 18.1647 3.36978 19.1303 3.95984 19.9375C4.5499 20.7448 5.36855 21.3566 6.31006 21.6939C6.92247 21.9253 7.57613 22.0274 8.22998 21.9937H15.79C16.4525 22.0218 17.1138 21.9179 17.7357 21.6881C18.3576 21.4582 18.9276 21.107 19.4125 20.6549C19.8973 20.2028 20.2874 19.6588 20.5599 19.0546C20.8325 18.4504 20.982 17.7981 21 17.1355V8.56872C21.0034 8.03873 20.8944 7.51404 20.6801 7.02928ZM16.0601 7.41915C15.9174 7.42047 15.7759 7.39353 15.6437 7.33986C15.5115 7.2862 15.3913 7.20687 15.2899 7.10649C15.1886 7.00611 15.1081 6.88664 15.0532 6.755C14.9983 6.62336 14.97 6.48215 14.97 6.33953V3.69052C15.63 3.85046 18.2 6.48947 18.76 6.92931C18.9256 7.06878 19.0675 7.23423 19.1801 7.41915H16.0601Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const PDFIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-red-500 w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M19 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19V5C21 3.9 20.1 3 19 3M9.5 11.5C9.5 12.3 8.8 13 8 13H7V15H5.5V9H8C8.8 9 9.5 9.7 9.5 10.5V11.5M14.5 13.5C14.5 14.3 13.8 15 13 15H10.5V9H13C13.8 9 14.5 9.7 14.5 10.5V13.5M18.5 10.5H17V11.5H18.5V13H17V15H15.5V9H18.5V10.5M12 10.5H13V13.5H12V10.5M7 10.5H8V11.5H7V10.5Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const DOCIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-blue-600 w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M15.5,17H14L12,9.5L10,17H8.5L6.1,7H7.8L9.34,14.5L11.3,7H12.7L14.67,14.5L16.2,7H17.9M19,3H5C3.89,3 3,3.89 3,5V19A2,2 0 0,0 5,21H19A2,2 0 0,0 21,19V5C21,3.89 20.1,3 19,3Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const ImagesIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-blue-600 w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M19 3H5C3.9 3 3 3.9 3 5V19C3 20.1 3.9 21 5 21H19C20.1 21 21 20.1 21 19V5C21 3.9 20.1 3 19 3M9 11.5C9 12.3 8.3 13 7.5 13H6.5V15H5V9H7.5C8.3 9 9 9.7 9 10.5V11.5M14 15H12.5L11.5 12.5V15H10V9H11.5L12.5 11.5V9H14V15M19 10.5H16.5V13.5H17.5V12H19V13.7C19 14.4 18.5 15 17.7 15H16.4C15.6 15 15.1 14.3 15.1 13.7V10.4C15 9.7 15.5 9 16.3 9H17.6C18.4 9 18.9 9.7 18.9 10.3V10.5H19M6.5 10.5H7.5V11.5H6.5V10.5Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const XMLIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-teal-500 w-[${size}px] h-[${size}px] ` + className}
      viewBox="0 0 24 24"
      xmlns="http://www.w3.org/2000/svg"
    >
      <path
        d="M19 3H5C3.89 3 3 3.89 3 5V19C3 20.11 3.89 21 5 21H19C20.11 21 21 20.11 21 19V5C21 3.89 20.11 3 19 3M8 15H6.5L6 13L5.5 15H4L4.75 12L4 9H5.5L6 11L6.5 9H8L7.25 12L8 15M15.5 15H14V10.5H13V14H11.5V10.5H10.5V15H9V11C9 9.9 9.9 9 11 9H13.5C14.61 9 15.5 9.9 15.5 11V15M20 15H17V9H18.5V13.5H20V15Z"
        fill="currentColor"
      />
    </svg>
  );
};

export const TXTIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-blue-600 w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      fill="currentColor"
      viewBox="0 0 24 24"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zM9.998 14.768H8.895v3.274h-.917v-3.274H6.893V14h3.105v.768zm2.725 3.274-.365-.731c-.15-.282-.246-.492-.359-.726h-.013c-.083.233-.185.443-.312.726l-.335.731h-1.045l1.171-2.045L10.336 14h1.05l.354.738c.121.245.21.443.306.671h.013c.096-.258.174-.438.276-.671l.341-.738h1.043l-1.139 1.973 1.198 2.069h-1.055zm4.384-3.274h-1.104v3.274h-.917v-3.274h-1.085V14h3.105v.768zM14 9h-1V4l5 5h-4z"></path>
    </svg>
  );
};

export const HTMLIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-orange-600 w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
    >
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm-1 2 5 5h-5V4zM8.531 18h-.76v-1.411H6.515V18h-.767v-3.373h.767v1.296h1.257v-1.296h.76V18zm3-2.732h-.921V18h-.766v-2.732h-.905v-.641h2.592v.641zM14.818 18l-.05-1.291c-.017-.405-.03-.896-.03-1.387h-.016c-.104.431-.245.911-.375 1.307l-.41 1.316h-.597l-.359-1.307a15.154 15.154 0 0 1-.306-1.316h-.011c-.021.456-.034.976-.059 1.396L12.545 18h-.705l.216-3.373h1.015l.331 1.126c.104.391.21.811.284 1.206h.017c.095-.391.209-.836.32-1.211l.359-1.121h.996L15.563 18h-.745zm3.434 0h-2.108v-3.373h.767v2.732h1.342V18z"></path>
    </svg>
  );
};

export const JSONIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`text-yellow-500 w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="200"
      height="200"
      viewBox="0 0 24 24"
    >
      <path
        fill="currentColor"
        d="M5 3h14a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2m3.25 8a1.25 1.25 0 1 0-2.5 0v2a1.25 1.25 0 1 0 2.5 0v-2m4.25-1.25a1.25 1.25 0 0 0-1.25 1.25v2a1.25 1.25 0 1 0 2.5 0v-2a1.25 1.25 0 0 0-1.25-1.25m4.25 1.25a1.25 1.25 0 1 0-2.5 0v2a1.25 1.25 0 1 0 2.5 0v-2z"
      />
    </svg>
  );
};

export const FolderMoveIcon = ({
  size = 24,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <svg
      style={{ width: `${size}px`, height: `${size}px` }}
      className={` w-[${size}px] h-[${size}px] ` + className}
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <circle cx="12" cy="12" r="10"></circle>
      <polyline points="12 8 8 12 12 16"></polyline>
      <line x1="16" y1="12" x2="8" y2="12"></line>
    </svg>
  );
};
