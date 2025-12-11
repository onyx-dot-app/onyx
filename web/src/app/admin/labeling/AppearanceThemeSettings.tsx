"use client";

import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Tabs, TabsList, TabsTrigger } from "@/refresh-components/tabs/tabs";
import Separator from "@/refresh-components/Separator";
import { Preview } from "./Preview";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
import InputImage from "@/refresh-components/inputs/InputImage";
import { useFormikContext } from "formik";
import { useRef } from "react";

interface CharacterCountProps {
  value: string;
  limit: number;
}

function CharacterCount({ value, limit }: CharacterCountProps) {
  const length = value?.length || 0;
  return (
    <Text text03 secondaryBody>
      ({length}/{limit} characters)
    </Text>
  );
}

interface AppearanceThemeSettingsProps {
  selectedLogo: File | null;
  setSelectedLogo: (file: File | null) => void;
  charLimits: {
    application_name: number;
    custom_greeting_message: number;
    custom_header_content: number;
    custom_lower_disclaimer_content: number;
    custom_popup_header: number;
    custom_popup_content: number;
  };
}

export function AppearanceThemeSettings({
  selectedLogo,
  setSelectedLogo,
  charLimits,
}: AppearanceThemeSettingsProps) {
  const { values, errors, setFieldValue } = useFormikContext<any>();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleLogoEdit = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setSelectedLogo(file);
    }
  };

  const handleLogoRemove = async () => {
    setFieldValue("use_custom_logo", false);
    setSelectedLogo(null);
  };

  const handleLogoRevert = () => {
    setSelectedLogo(null);
  };

  const getLogoSrc = () => {
    if (selectedLogo) {
      return URL.createObjectURL(selectedLogo);
    }
    if (values.use_custom_logo) {
      return `/api/enterprise-settings/logo?u=${Date.now()}`;
    }
    return undefined;
  };

  return (
    <div className="flex flex-col gap-4 w-full">
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileChange}
        accept="image/png,image/jpeg,image/jpg"
        style={{ display: "none" }}
      />

      <div className="flex gap-10 items-center">
        <div className="flex flex-col gap-4 w-full">
          <FormField state={errors.application_name ? "error" : "idle"}>
            <FormField.Label
              rightAction={
                <CharacterCount
                  value={values.application_name}
                  limit={charLimits.application_name}
                />
              }
            >
              Application Display Name
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn
                showClearButton
                value={values.application_name}
                onChange={(e) =>
                  setFieldValue("application_name", e.target.value)
                }
              />
            </FormField.Control>
            <FormField.Description>
              This name will show across the app and replace "Onyx" in the UI.
            </FormField.Description>
            <FormField.Message
              messages={{ error: errors.application_name as string }}
            />
          </FormField>

          <FormField state="idle">
            <FormField.Label>Logo Display Style</FormField.Label>
            <FormField.Control>
              <Tabs
                value={values.logo_display_style}
                onValueChange={(value) =>
                  setFieldValue("logo_display_style", value)
                }
              >
                <TabsList className="w-full grid grid-cols-3">
                  <TabsTrigger value="logo_and_name">Logo & Name</TabsTrigger>
                  <TabsTrigger value="logo_only">Logo Only</TabsTrigger>
                  <TabsTrigger value="none">None</TabsTrigger>
                </TabsList>
              </Tabs>
            </FormField.Control>
            <FormField.Description>
              Show both your application logo and name on the sidebar.
            </FormField.Description>
          </FormField>
        </div>

        <div>
          <InputImage
            content={getLogoSrc() ? "image" : "placeholder"}
            src={getLogoSrc()}
            onEdit={handleLogoEdit}
            showRemove={values.use_custom_logo}
            showRevert={!!selectedLogo}
            onRemove={handleLogoRemove}
            onRevert={handleLogoRevert}
          />
        </div>
      </div>

      <Separator className="my-4" />

      <Preview
        className="mb-8"
        logoDisplayStyle={values.logo_display_style}
        applicationDisplayName={values.application_name || "Onyx"}
        chat_footer_content={
          values.custom_lower_disclaimer_content || "Chat Footer Content"
        }
        chat_header_content={
          values.custom_header_content || "Chat Header Content"
        }
        greeting_message={
          values.custom_greeting_message || "Welcome to Acme Chat"
        }
        logoSrc={getLogoSrc()}
      />

      <FormField state={errors.custom_greeting_message ? "error" : "idle"}>
        <FormField.Label
          rightAction={
            <CharacterCount
              value={values.custom_greeting_message}
              limit={charLimits.custom_greeting_message}
            />
          }
        >
          Greeting Message
        </FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn
            showClearButton
            value={values.custom_greeting_message}
            onChange={(e) =>
              setFieldValue("custom_greeting_message", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Description>
          Add a short message to the home page.
        </FormField.Description>
        <FormField.Message
          messages={{ error: errors.custom_greeting_message as string }}
        />
      </FormField>

      <FormField state={errors.custom_header_content ? "error" : "idle"}>
        <FormField.Label
          rightAction={
            <CharacterCount
              value={values.custom_header_content}
              limit={charLimits.custom_header_content}
            />
          }
        >
          Chat Header Text
        </FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn
            showClearButton
            value={values.custom_header_content}
            onChange={(e) =>
              setFieldValue("custom_header_content", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Message
          messages={{ error: errors.custom_header_content as string }}
        />
      </FormField>

      <FormField
        state={errors.custom_lower_disclaimer_content ? "error" : "idle"}
      >
        <FormField.Label
          rightAction={
            <CharacterCount
              value={values.custom_lower_disclaimer_content}
              limit={charLimits.custom_lower_disclaimer_content}
            />
          }
        >
          Chat Footer Text
        </FormField.Label>
        <FormField.Control asChild>
          <InputTextArea
            rows={3}
            placeholder="Add markdown content"
            value={values.custom_lower_disclaimer_content}
            onChange={(e) =>
              setFieldValue("custom_lower_disclaimer_content", e.target.value)
            }
          />
        </FormField.Control>
        <FormField.Description>
          Add markdown content for disclaimers or additional information.
        </FormField.Description>
        <FormField.Message
          messages={{ error: errors.custom_lower_disclaimer_content as string }}
        />
      </FormField>

      <Separator className="my-4" />

      <div className="flex flex-col gap-4 p-4 bg-background-tint-00 rounded-16">
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>Show First Visit Notice</FormField.Label>
            <FormField.Control>
              <Switch
                checked={values.show_first_visit_notice}
                onCheckedChange={(checked) =>
                  setFieldValue("show_first_visit_notice", checked)
                }
              />
            </FormField.Control>
          </div>
          <FormField.Description>
            Show a one-time pop-up for new users at their first visit.
          </FormField.Description>
        </FormField>

        {values.show_first_visit_notice && (
          <>
            <FormField state={errors.custom_popup_header ? "error" : "idle"}>
              <FormField.Label
                rightAction={
                  <CharacterCount
                    value={values.custom_popup_header}
                    limit={charLimits.custom_popup_header}
                  />
                }
              >
                Notice Header
              </FormField.Label>
              <FormField.Control asChild>
                <InputTypeIn
                  showClearButton
                  value={values.custom_popup_header}
                  onChange={(e) =>
                    setFieldValue("custom_popup_header", e.target.value)
                  }
                />
              </FormField.Control>
              <FormField.Message
                messages={{ error: errors.custom_popup_header as string }}
              />
            </FormField>

            <FormField state={errors.custom_popup_content ? "error" : "idle"}>
              <FormField.Label
                rightAction={
                  <CharacterCount
                    value={values.custom_popup_content}
                    limit={charLimits.custom_popup_content}
                  />
                }
              >
                Notice Content
              </FormField.Label>
              <FormField.Control asChild>
                <InputTextArea
                  rows={3}
                  placeholder="Add markdown content"
                  value={values.custom_popup_content}
                  onChange={(e) =>
                    setFieldValue("custom_popup_content", e.target.value)
                  }
                />
              </FormField.Control>
              <FormField.Message
                messages={{ error: errors.custom_popup_content as string }}
              />
            </FormField>

            <FormField state="idle" className="gap-0">
              <div className="flex justify-between items-center">
                <FormField.Label>Require Consent to Notice</FormField.Label>
                <FormField.Control>
                  <Switch
                    checked={values.enable_consent_screen}
                    onCheckedChange={(checked) =>
                      setFieldValue("enable_consent_screen", checked)
                    }
                  />
                </FormField.Control>
              </div>
              <FormField.Description>
                Require the user to read and agree to the notice before
                accessing the application.
              </FormField.Description>
            </FormField>
          </>
        )}
      </div>
    </div>
  );
}
