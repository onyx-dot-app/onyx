import Link from "next/link";
import { Button } from "@/components/ui/button";
import { FiPlusCircle } from "react-icons/fi";
interface CreateButtonProps {
  href?: string;
  onClick?: () => void;
  text?: string;
  icon?: React.ReactNode;
}

export default function CreateButton({
  href,
  onClick,
  text = "Create",
  icon = <FiPlusCircle />,
}: CreateButtonProps) {
  const content = (
    <Button className="font-normal mt-2" variant="create" onClick={onClick}>
      {icon}
      {text}
    </Button>
  );

  if (href) {
    return <Link href={href}>{content}</Link>;
  }

  return content;
}
