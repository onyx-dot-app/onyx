import Link from "next/link";
import { Button } from "@/components/ui/button";
import { FiPlusCircle } from "react-icons/fi";

interface CreateButtonProps {
  href: string;
  text?: string;
}

export default function CreateButton({
  href,
  text = "Create",
}: CreateButtonProps) {
  return (
    <Link href={href}>
      <Button className="font-normal mt-2" variant="create">
        <FiPlusCircle />
        {text}
      </Button>
    </Link>
  );
}
