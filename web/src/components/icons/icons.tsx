"use client";

import {
  Notebook,
  Key,
  Trash,
  XSquare,
  LinkBreak,
  Link,
  Plug,
  Brain,
  X,
  Question,
  Users,
  Gear,
  ArrowSquareOut,
} from "@phosphor-icons/react";
import {
  FiCheck,
  FiChevronsDown,
  FiChevronsUp,
  FiEdit,
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
  FiZoomIn,
  FiCopy,
  FiBookmark,
  FiCpu,
  FiInfo,
  FiUploadCloud,
  FiUsers,
} from "react-icons/fi";
import { SiBookstack } from "react-icons/si";
import Image from "next/image";
import jiraSVG from "../../../public/Jira.svg";
import confluenceSVG from "../../../public/Confluence.svg";
import guruIcon from "../../../public/Guru.svg";
import gongIcon from "../../../public/Gong.png";
import requestTrackerIcon from "../../../public/RequestTracker.png";
import zulipIcon from "../../../public/Zulip.png";
import linearIcon from "../../../public/Linear.png";
import hubSpotIcon from "../../../public/HubSpot.png";
import document360Icon from "../../../public/Document360.png";
import googleSitesIcon from "../../../public/GoogleSites.png";
import zendeskIcon from "../../../public/Zendesk.svg";
import sharepointIcon from "../../../public/Sharepoint.png";
import discourseIcon from "../../../public/Discourse.png";
import { FaRobot } from "react-icons/fa";

interface IconProps {
  size?: number;
  className?: string;
}

export const defaultTailwindCSS = "my-auto flex flex-shrink-0 text-default";
export const defaultTailwindCSSBlue = "my-auto flex flex-shrink-0 text-link";

export const PlugIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Plug size={size} className={className} />;
};

export const NotebookIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Notebook size={size} className={className} />;
};

export const KeyIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Key size={size} className={className} />;
};

export const UsersIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <Users size={size} className={className} />;
};

export const GroupsIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiUsers size={size} className={className} />;
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

export const GlobeIcon = ({
  size = 16,
  className = defaultTailwindCSSBlue,
}: IconProps) => {
  return <FiGlobe size={size} className={className} />;
};

export const FileIcon = ({
  size = 16,
  className = defaultTailwindCSSBlue,
}: IconProps) => {
  return <FiFile size={size} className={className} />;
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
  return <FiEdit size={size} className={className} />;
};

export const XIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <X size={size} className={className} />;
};

export const ThumbsUpIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiThumbsUp size={size} className={className} />;
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

export const CheckmarkIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiCheck size={size} className={className} />;
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

export const ZoomInIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiZoomIn size={size} className={className} />;
};

export const CopyIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiCopy size={size} className={className} />;
};

export const BookmarkIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiBookmark size={size} className={className} />;
};

export const CPUIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiCpu size={size} className={className} />;
};

export const RobotIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FaRobot size={size} className={className} />;
};

export const ConnectorIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <FiUploadCloud size={size} className={className} />;
};

//
//  COMPANY LOGOS
//

export const LoopioIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] dark:invert ` + className}
    >
      <Image src="/Loopio.png" alt="Logo" width="96" height="96" />
    </div>
  );
};

export const SlackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/Slack.png" alt="Logo" width="96" height="96" />
    </div>
  );
};
export const GitlabIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/Gitlab.png" alt="Logo" width="96" height="96" />
    </div>
  );
};
export const GithubIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/Github.png" alt="Logo" width="96" height="96" />
    </div>
  );
};

export const GmailIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/Gmail.png" alt="Logo" width="96" height="96" />
    </div>
  );
};

export const GoogleDriveIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/GoogleDrive.png" alt="Logo" width="96" height="96" />
    </div>
  );
};

export const BookstackIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return <SiBookstack size={size} className={className + " text-[#0288D1]"} />;
};

export const ConfluenceIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size + 4}px`, height: `${size + 4}px` }}
      className={`w-[${size + 4}px] h-[${size + 4}px] -m-0.5 ` + className}
    >
      <Image src={confluenceSVG} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const JiraIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  // Jira Icon has a bit more surrounding whitespace than other icons, which is why we need to adjust it here
  return (
    <div
      style={{ width: `${size + 4}px`, height: `${size + 4}px` }}
      className={`w-[${size + 4}px] h-[${size + 4}px] -m-0.5 ` + className}
    >
      <Image src={jiraSVG} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const ZulipIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src={zulipIcon} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const ProductboardIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/Productboard.webp" alt="Logo" width="96" height="96" />
    </div>
  );
};

export const LinearIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      // Linear Icon has a bit more surrounding whitespace than other icons, which is why we need to adjust it here
      style={{ width: `${size + 4}px`, height: `${size + 4}px` }}
      className={`w-[${size + 4}px] h-[${size + 4}px] -m-0.5 ` + className}
    >
      <Image src={linearIcon} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const SlabIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src="/SlabLogo.png" alt="Logo" width="96" height="96" />
  </div>
);

export const NotionIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src="/Notion.png" alt="Logo" width="96" height="96" />
    </div>
  );
};

export const GuruIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src={guruIcon} alt="Logo" width="96" height="96" />
  </div>
);

export const RequestTrackerIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src={requestTrackerIcon} alt="Logo" width="96" height="96" />
  </div>
);

export const SharepointIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src={sharepointIcon} alt="Logo" width="96" height="96" />
  </div>
);

export const GongIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src={gongIcon} alt="Logo" width="96" height="96" />
  </div>
);

export const HubSpotIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      // HubSpot Icon has a bit more surrounding whitespace than other icons, which is why we need to adjust it here
      style={{ width: `${size + 4}px`, height: `${size + 4}px` }}
      className={`w-[${size + 4}px] h-[${size + 4}px] -m-0.5 ` + className}
    >
      <Image src={hubSpotIcon} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const Document360Icon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size + 4}px`, height: `${size + 4}px` }}
      className={`w-[${size + 4}px] h-[${size + 4}px] -m-0.5 ` + className}
    >
      <Image src={document360Icon} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const GoogleSitesIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => {
  return (
    <div
      style={{ width: `${size}px`, height: `${size}px` }}
      className={`w-[${size}px] h-[${size}px] ` + className}
    >
      <Image src={googleSitesIcon} alt="Logo" width="96" height="96" />
    </div>
  );
};

export const ZendeskIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src={zendeskIcon} alt="Logo" width="96" height="96" />
  </div>
);

export const DiscourseIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src={discourseIcon} alt="Logo" width="96" height="96" />
  </div>
);

export const AxeroIcon = ({
  size = 16,
  className = defaultTailwindCSS,
}: IconProps) => (
  <div
    style={{ width: `${size}px`, height: `${size}px` }}
    className={`w-[${size}px] h-[${size}px] ` + className}
  >
    <Image src="/Axero.jpeg" alt="Logo" width="96" height="96" />
  </div>
);
