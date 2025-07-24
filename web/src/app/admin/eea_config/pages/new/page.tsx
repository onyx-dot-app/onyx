"use client";
import { use } from "react";

import { ErrorCallout } from "@/components/ErrorCallout";
//import { useDocumentSets } from "../hooks";
import {
  useConnectorCredentialIndexingStatus,
  useUserGroups,
} from "@/lib/hooks";
import { ThreeDotsLoader } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import { BookmarkIcon } from "@/components/icons/icons";
import { BackButton } from "@/components/BackButton";
//import { DocumentSetCreationForm } from "../DocumentSetCreationForm";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { usePopup } from "@/components/admin/connectors/Popup";
import { LoadingAnimation } from "@/components/Loading";
import { FiCpu } from "react-icons/fi";
// import { Text, Title, Button } from "@tremor/react";
import { Button } from "@/components/ui/button";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";

import { Form, Formik, Field } from "formik";
import { TextFormField } from "@/components/Field";

const GET_EEA_CONFIG_URL = "/api/eea_config/get_eea_config";
const SET_EEA_CONFIG_URL = "/api/eea_config/set_eea_config";

export default function Page(props: { params: Promise<{ pageTitle: string }> }) {
  const params = use(props.params);
  const { data, isLoading, error } = useSWR<{ config: string }>(
    GET_EEA_CONFIG_URL,
    errorHandlingFetcher
  );
  let config_json = {"pages":{}};
  if (data){
    config_json = JSON.parse(data?.config);
  }
  let initial_page_title = "";
  let initial_page_text = ""
  if (params?.pageTitle != undefined){
    initial_page_title = params?.pageTitle;
    let pages: any = config_json?.pages || {};
    initial_page_text = pages[initial_page_title];
  }
  const { popup, setPopup } = usePopup();
  if (isLoading) {
    return <LoadingAnimation text="Loading" />;
  }
  return (
    <div>
      {popup}
      <BackButton />
      <div className="mx-auto container">
        <AdminPageTitle
          title="Customize Layout"
          icon={<FiCpu size={32} className="my-auto" />}
        />
        <Title className="mb-2 mt-6">Customize footer:</Title>
        <Text className="mb-2">
          Footer.
        </Text>
        <div className="border rounded-md border-border p-3">
          <Formik
            initialValues={{ page_title: initial_page_title, page_text:initial_page_text}}
            onSubmit={async ({ page_title, page_text }, formikHelpers) => {
              console.log(config_json)
              let isDuplicated = false;
              for (const [key, value] of Object.entries(config_json?.pages || {})) {
                if ((key === page_title) && (key !== initial_page_title)){
                  isDuplicated = true
                }
              }
              if (isDuplicated){
                setPopup({ message: "Duplicated page", type: "error" });
                return;
              } else{
                let pages: any = config_json?.pages || {};
                if (initial_page_title !== ""){
                  delete(pages[initial_page_title]);
                }
                pages[page_title] = page_text;
                config_json.pages = pages;
              }
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
                setPopup({
                  message: `Error while saving the page: ${response.status} - ${response.statusText}`,
                  type: "error",
                });
                return;
              } else {
                setPopup({ message: "Page saved", type: "success" });
                return;
              }
            }}
          >
            <Form>
              <TextFormField
                name="page_title"
                label="Page:"
                isTextArea={false}
              />
              <TextFormField
                name="page_text"
                label="Page Text:"
                isTextArea={true}
              />

              <div className="flex">
                <Button type="submit" className="w-48 mx-auto">
                  Submit
                </Button>
              </div>
            </Form>
          </Formik>
        </div>
      </div>
      
    </div>
  );
}
