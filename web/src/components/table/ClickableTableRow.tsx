"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { TableRow } from "@/components/ui/table";

interface ClickableTableRowProps {
  url: string;
  children: React.ReactNode;
  [key: string]: any;
}

export function ClickableTableRow({
  url,
  children,
  ...props
}: ClickableTableRowProps) {
  const router = useRouter();

  useEffect(() => {
    router.prefetch(url);
  }, [router, url]);

  const navigate = () => {
    router.push(url);
  };

  return (
    <TableRow {...props} onClick={navigate}>
      {children}
    </TableRow>
  );
}
