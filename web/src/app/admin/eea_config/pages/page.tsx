"use client";

import { LoadingAnimation } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { errorHandlingFetcher } from "@/lib/fetcher";
//import {TableHeaderCell } from "@tremor/react";

import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";


import { FiCpu, FiEdit } from "react-icons/fi";
import useSWR from "swr";
import { Form, Formik, Field } from "formik";
import { TextFormField } from "@/components/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import Link from "next/link";
import { useState } from "react";
import { DeleteButton } from "@/components/DeleteButton";
import { useRouter } from "next/navigation";
import { BookmarkIcon, InfoIcon } from "@/components/icons/icons";
import { PageSelector } from "@/components/PageSelector";
import { usePagesList } from "./hooks";

const GET_EEA_CONFIG_URL = "/api/eea_config/get_eea_config";
const SET_EEA_CONFIG_URL = "/api/eea_config/set_eea_config";
const numToDisplay = 50;


const EditRow = ({ pageTitle }: { pageTitle: string }) => {
  const router = useRouter();

  return (
    <div className="relative flex">
      <div
        className={
          "text-emphasis font-medium my-auto p-1 hover:bg-hover-light flex cursor-pointer select-none cursor-pointer"
        }
        onClick={() => {
            router.push(`/admin/eea_config/pages/${pageTitle}`);
        }}
        // onMouseEnter={() => {
        //     //setIsSyncingTooltipOpen(true);
        // }}
        // onMouseLeave={() => {
        //     //setIsSyncingTooltipOpen(false);
        // }}
      >
        <FiEdit className="text-emphasis mr-1 my-auto" />
        {pageTitle}
      </div>
    </div>
  );
};

interface PagesTableProps {
  pages: any [];
  config_json: {"pages":{}};
  refresh: () => void;
}
const PagesTable = ({
  pages,
  config_json,
  refresh,
}: PagesTableProps) => {
  const [page, setPage] = useState(1);

  // sort by name for consistent ordering
  pages.sort((a, b) => {
    if (a < b) {
      return -1;
    } else if (a > b) {
      return 1;
    } else {
      return 0;
    }
  });

  return (
    <div>
      <Title>Existing Pages</Title>
      <Table className="overflow-visible mt-2">
        <TableHead>
          <TableRow>
            <TableHeader>Name</TableHeader>
            <TableHeader>Delete</TableHeader>
          </TableRow>
        </TableHead>
        <TableBody>
          {pages
            .slice((page - 1) * numToDisplay, page * numToDisplay)
            .map((pageTitle) => {
              return (
                <TableRow key={pageTitle}>
                  <TableCell className="whitespace-normal break-all">
                    <div className="flex gap-x-1 text-emphasis">
                      <EditRow pageTitle={pageTitle} />
                    </div>
                  </TableCell>

                  {/* <TableCell className="whitespace-normal break-all">
                    <div className="flex gap-x-1 text-emphasis">
                      {pageTitle}
                    </div>
                  </TableCell> */}
                  {/* <TableCell>
                    
                  </TableCell> */}
                  <TableCell>
                    <DeleteButton
                      onClick={async () => {
                        let pages = (config_json as any)?.pages;
                        delete pages[pageTitle];
                        config_json.pages = pages;
                        
                        const body = JSON.stringify({ config: JSON.stringify(config_json) });
                        const response = await fetch(SET_EEA_CONFIG_URL, {
                          method: "POST",
                          headers: {
                            "Content-Type": "application/json",
                          },
                          body: body,
                        });
                        console.log(response);
                        if (!response?.ok) {
                          console.log(`Error while deleting the page: ${response.status} - ${response.statusText}`);
                          refresh();
                          return;
                        } else {
                          console.log("Page deleted");
                          refresh();
                          return;
                        }
                        //refresh();
                      }}
                    />
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>

      <div className="mt-3 flex">
        <div className="mx-auto">
          <PageSelector
            totalPages={Math.ceil(pages.length / numToDisplay)}
            currentPage={page}
            onPageChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
};

const Page = () => {
  const { data, isLoading, error } = useSWR<{ config: string }>(
    GET_EEA_CONFIG_URL,
    errorHandlingFetcher
  );
  const {
    refreshPagesList,
  } = usePagesList();

  let config_json = {"pages":[]};
  if (data){
    console.log(data)
    config_json = JSON.parse(data?.config);
  }

  const { popup, setPopup } = usePopup();
  
  if (isLoading) {
    return <LoadingAnimation text="Loading" />;
  }

  const pages = Object.keys(config_json?.pages || {}) || [];
  return (
    <>
    <div className="mb-8">
      {popup}
      <div className="mx-auto container">
      <AdminPageTitle icon={<FiCpu size={32} />} title="Pages configuration" />
      <Text className="mb-3">
        <b>User defined pages</b> allow you to create pages.
      </Text>

      <div className="mb-3"></div>

      <div className="flex mb-6">
        <Link href="/admin/eea_config/pages/new">
          <Button color="green" className="ml-2 my-auto">
            New Page
          </Button>
        </Link>
      </div>

      {pages.length > 0 && (
        <>
          <Separator />
          <PagesTable
            pages={pages}
            config_json={config_json}
            refresh={refreshPagesList}
          />
        </>
      )}
    </div>
    </div>
    </>
  );
};

export default Page;
