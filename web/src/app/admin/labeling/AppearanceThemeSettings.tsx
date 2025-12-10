"use client";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { Tabs, TabsList, TabsTrigger } from "@/refresh-components/tabs/tabs";
import Separator from "@/refresh-components/Separator";
import { Preview } from "./Preview";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import Switch from "@/refresh-components/inputs/Switch";
import Text from "@/refresh-components/texts/Text";
export function AppearanceThemeSettings() {
  return (
    <div className="flex flex-col gap-4 w-full">
      <div className="flex gap-10 items-center">
        <div className="flex flex-col gap-4 w-full">
          <FormField state="idle">
            <FormField.Label
              rightAction={
                <Text text03 secondaryBody>
                  (9/50 characters)
                </Text>
              }
            >
              Application Display Name
            </FormField.Label>
            <FormField.Control asChild>
              <InputTypeIn showClearButton />
            </FormField.Control>
            <FormField.Description>
              This name will show across the app and replace “Onyx” in the UI.
            </FormField.Description>
          </FormField>
          <FormField state="idle">
            <FormField.Label>Logo Display Style</FormField.Label>
            <FormField.Control>
              <Tabs value="logo_and_name">
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
        <div className="w-28 h-28 bg-background-neutral-04 rounded-full">
          {/* TODO: Add logo here */}
        </div>
      </div>
      <Separator className="my-4" />
      <Preview
        className="mb-8"
        logoDisplayStyle="logo_and_name"
        applicationDisplayName="Onyx"
        chat_footer_content="Chat Footer Content"
        chat_header_content="Chat Header Content"
        greeting_message="Welcome to Acme Chat"
      />
      <FormField state="idle">
        <FormField.Label>Greeting Message</FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn showClearButton />
        </FormField.Control>
        <FormField.Description>
          Add a short message to the home page.
        </FormField.Description>
      </FormField>
      <FormField state="idle">
        <FormField.Label>Chat Header Text</FormField.Label>
        <FormField.Control asChild>
          <InputTypeIn showClearButton />
        </FormField.Control>
      </FormField>
      <FormField state="idle">
        <FormField.Label>Chat Footer Text</FormField.Label>
        <FormField.Control asChild>
          <InputTextArea rows={3} placeholder="Add markdown content" />
        </FormField.Control>
        <FormField.Description>
          Add markdown content for disclaimers or additional information.
        </FormField.Description>
      </FormField>
      <Separator className="my-4" />
      <div className="flex flex-col gap-4 p-4 bg-background-tint-00 rounded-16">
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>Show First Visit Notice</FormField.Label>
            <FormField.Control>
              <Switch />
            </FormField.Control>
          </div>
          <FormField.Description>
            Show a one-time pop-up for new users at their first visit.
          </FormField.Description>
        </FormField>
        <FormField state="idle">
          <FormField.Label>Notice Header</FormField.Label>
          <FormField.Control asChild>
            <InputTypeIn showClearButton />
          </FormField.Control>
        </FormField>
        <FormField state="idle">
          <FormField.Label>Notice Content</FormField.Label>
          <FormField.Control asChild>
            <InputTextArea rows={3} placeholder="Add markdown content" />
          </FormField.Control>
        </FormField>
        <FormField state="idle" className="gap-0">
          <div className="flex justify-between items-center">
            <FormField.Label>Require Consent to Notice</FormField.Label>
            <FormField.Control>
              <Switch />
            </FormField.Control>
          </div>
          <FormField.Description>
            Require the user to read and agree to the notice before accessing
            the application.
          </FormField.Description>
        </FormField>
      </div>
    </div>
  );
}
