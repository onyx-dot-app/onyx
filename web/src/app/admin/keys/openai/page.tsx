"use client";

import { Form, Formik } from "formik";
import { useEffect, useState } from "react";
import { LoadingAnimation } from "@/components/Loading";
import { AdminPageTitle } from "@/components/admin/Title";
import {
  BooleanFormField,
  SectionHeader,
  TextFormField,
} from "@/components/admin/connectors/Field";
import { Popup } from "@/components/admin/connectors/Popup";
import { TrashIcon } from "@/components/icons/icons";
import { ApiKeyForm } from "@/components/openai/ApiKeyForm";
import { GEN_AI_API_KEY_URL } from "@/components/openai/constants";
import { fetcher } from "@/lib/fetcher";
import { Button, Divider, Text, Title } from "@tremor/react";
import { FiCpu } from "react-icons/fi";
import useSWR, { mutate } from "swr";

const ExistingKeys = () => {
  const { data, isLoading, error } = useSWR<{ api_key: string }>(
    GEN_AI_API_KEY_URL,
    fetcher
  );

  if (isLoading) {
    return <LoadingAnimation text="Loading" />;
  }

  if (error) {
    return <div className="text-error">Error loading existing keys</div>;
  }

  if (!data?.api_key) {
    return null;
  }

  return (
    <div>
      <Title className="mb-2">Existing Key</Title>
      <div className="flex mb-1">
        <p className="text-sm italic my-auto">sk- ****...**{data?.api_key}</p>
        <button
          className="ml-1 my-auto hover:bg-hover rounded p-1"
          onClick={async () => {
            await fetch(GEN_AI_API_KEY_URL, {
              method: "DELETE",
            });
            window.location.reload();
          }}
        >
          <TrashIcon />
        </button>
      </div>
    </div>
  );
};

const LLMOptions = () => {
  const [popup, setPopup] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);

  const [tokenBudgetGloballyEnabled, setTokenBudgetGloballyEnabled] =
    useState(false);
  const [initialValues, setInitialValues] = useState({
    enable_token_budget: false,
    token_budget: "",
    token_budget_time_period: "",
  });

  const fetchConfig = async () => {
    const response = await fetch("/api/manage/admin/token-budget-settings");
    if (response.ok) {
      const config = await response.json();
      // Assuming the config object directly matches the structure needed for initialValues
      setInitialValues({
        enable_token_budget: config.enable_token_budget || false,
        token_budget: config.token_budget || "",
        token_budget_time_period: config.token_budget_time_period || "",
      });
      setTokenBudgetGloballyEnabled(true);
    } else {
      // Handle error or provide fallback values
      setPopup({
        message: "Failed to load current LLM options.",
        type: "error",
      });
    }
  };

  // Fetch current config when the component mounts
  useEffect(() => {
    fetchConfig();
  }, []);

  if (!tokenBudgetGloballyEnabled) {
    return null;
  }

  return (
    <>
      {popup && <Popup message={popup.message} type={popup.type} />}
      <Formik
        enableReinitialize={true}
        initialValues={initialValues}
        onSubmit={async (values) => {
          const response = await fetch(
            "/api/manage/admin/token-budget-settings",
            {
              method: "PUT",
              headers: {
                "Content-Type": "application/json",
              },
              body: JSON.stringify(values),
            }
          );
          if (response.ok) {
            setPopup({
              message: "Updated LLM Options",
              type: "success",
            });
            await fetchConfig();
          } else {
            const body = await response.json();
            if (body.detail) {
              setPopup({ message: body.detail, type: "error" });
            } else {
              setPopup({
                message: "Unable to update LLM options.",
                type: "error",
              });
            }
            setTimeout(() => {
              setPopup(null);
            }, 4000);
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => {
          return (
            <Form>
              <Divider />
              <>
                <SectionHeader>Token Budget</SectionHeader>
                <Text>
                  Set a maximum token use per time period. If the token budget
                  is exceeded, Danswer will not be able to respond to queries
                  until the next time period.
                </Text>
                <br />
                <BooleanFormField
                  name="enable_token_budget"
                  label="Enable Token Budget"
                  subtext="If enabled, Danswer will be limited to the token budget specified below."
                  onChange={(e) => {
                    setFieldValue("enable_token_budget", e.target.checked);
                  }}
                />
                {values.enable_token_budget && (
                  <>
                    <TextFormField
                      name="token_budget"
                      label="Token Budget"
                      subtext={
                        <div>
                          How many tokens (in thousands) can be used per time
                          period? If unspecified, no limit will be set.
                        </div>
                      }
                      onChange={(e) => {
                        const value = e.target.value;
                        // Allow only integer values
                        if (value === "" || /^[0-9]+$/.test(value)) {
                          setFieldValue("token_budget", value);
                        }
                      }}
                    />
                    <TextFormField
                      name="token_budget_time_period"
                      label="Token Budget Time Period (hours)"
                      subtext={
                        <div>
                          Specify the length of the time period, in hours, over
                          which the token budget will be applied.
                        </div>
                      }
                      onChange={(e) => {
                        const value = e.target.value;
                        // Allow only integer values
                        if (value === "" || /^[0-9]+$/.test(value)) {
                          setFieldValue("token_budget_time_period", value);
                        }
                      }}
                    />
                  </>
                )}
              </>
              <div className="flex">
                <Button
                  className="w-64 mx-auto"
                  type="submit"
                  disabled={isSubmitting}
                >
                  Submit
                </Button>
              </div>
            </Form>
          );
        }}
      </Formik>
    </>
  );
};

const Page = () => {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="LLM Options"
        icon={<FiCpu size={32} className="my-auto" />}
      />

      <SectionHeader>LLM Keys</SectionHeader>

      <ExistingKeys />

      <Title className="mb-2 mt-6">Update Key</Title>
      <Text className="mb-2">
        Specify an OpenAI API key and click the &quot;Submit&quot; button.
      </Text>
      <div className="border rounded-md border-border p-3">
        <ApiKeyForm
          handleResponse={(response) => {
            if (response.ok) {
              mutate(GEN_AI_API_KEY_URL);
            }
          }}
        />
      </div>
      <LLMOptions />
    </div>
  );
};

export default Page;
