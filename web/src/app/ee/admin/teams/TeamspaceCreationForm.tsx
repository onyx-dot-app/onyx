import { Form, Formik } from "formik";
import * as Yup from "yup";
import {
  ConnectorIndexingStatus,
  User,
  Teamspace,
  DocumentSet,
} from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import { createTeamspace } from "./lib";
import { UserEditor } from "./UserEditor";
import { ConnectorEditor } from "./ConnectorEditor";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { useDocumentSets } from "@/app/admin/documents/sets/hooks";
import { Assistant } from "@/app/admin/assistants/interfaces";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { FileUpload } from "@/components/admin/connectors/FileUpload";
import { useState } from "react";
import { DocumentSets } from "./DocumentSets";
import { Assistants } from "./Assistants";

interface TeamspaceCreationFormProps {
  onClose: () => void;
  users: User[];
  ccPairs: ConnectorIndexingStatus<any, any>[];
  existingTeamspace?: Teamspace;
  assistants: Assistant[];
  documentSets: DocumentSet[] | undefined;
}

export const TeamspaceCreationForm = ({
  onClose,
  users,
  ccPairs,
  existingTeamspace,
  assistants,
  documentSets,
}: TeamspaceCreationFormProps) => {
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const isUpdate = existingTeamspace !== undefined;
  const { toast } = useToast();

  return (
    <div>
      <Formik
        initialValues={{
          name: existingTeamspace ? existingTeamspace.name : "",
          user_ids: [] as string[],
          cc_pair_ids: [] as number[],
          document_set_ids: [] as number[],
          assistant_ids: [] as string[],
        }}
        validationSchema={Yup.object().shape({
          name: Yup.string().required("Please enter a name for the group"),
          user_ids: Yup.array().of(Yup.string().required()),
          cc_pair_ids: Yup.array().of(Yup.number().required()),
          document_set_ids: Yup.array().of(Yup.number().required()),
          assistant_ids: Yup.array().of(Yup.number().required()),
        })}
        onSubmit={async (values, formikHelpers) => {
          formikHelpers.setSubmitting(true);

          console.log("Submitted values:", values);

          let response;
          response = await createTeamspace(values);
          formikHelpers.setSubmitting(false);
          if (response.ok) {
            toast({
              title: isUpdate ? "Teamspace Updated!" : "Teamspace Created!",
              description: isUpdate
                ? "Your teamspace has been updated successfully."
                : "Your new teamspace has been created successfully.",
              variant: "success",
            });

            onClose();
          } else {
            const responseJson = await response.json();
            const errorMsg = responseJson.detail || responseJson.message;
            toast({
              title: "Operation Failed",
              description: isUpdate
                ? `Could not update the teamspace: ${errorMsg}`
                : `Could not create the teamspace: ${errorMsg}`,
              variant: "destructive",
            });
          }
        }}
      >
        {({ isSubmitting, values, setFieldValue }) => (
          <Form>
            <div className="pt-8 space-y-6">
              <div className="flex justify-between gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Teamspace Name
                </p>
                <TextFormField
                  name="name"
                  placeholder="A name for the Teamspace"
                  disabled={isUpdate}
                  autoCompleteDisabled={true}
                  fullWidth
                />
              </div>

              <div className="flex justify-between gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Teamspace Logo
                </p>
                <div className="flex items-center gap-2 w-full">
                  <FileUpload
                    selectedFiles={selectedFiles}
                    setSelectedFiles={setSelectedFiles}
                  />
                </div>
              </div>

              <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Select Users
                </p>
                <div className="w-full">
                  <UserEditor
                    selectedUserIds={values.user_ids}
                    setSelectedUserIds={(userIds) =>
                      setFieldValue("user_ids", userIds)
                    }
                    allUsers={users}
                    existingUsers={[]}
                  />
                </div>
              </div>

              <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Select assistants
                </p>
                <div className="w-full">
                  <Assistants
                    assistants={assistants}
                    onSelect={(selectedAssistantIds) => {
                      setFieldValue("assistant_ids", selectedAssistantIds);
                    }}
                  />
                </div>
              </div>

              {/*  <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Security Setting
                </p>
                <div className="flex items-center gap-2 w-full">
                  <Switch />
                  <p className="text-sm">
                    Activates private mode, chat and search activities
                    won&rsquo;t appear in the workspace admin&rsquo;s query
                    history
                  </p>
                </div>
              </div> */}

              {/*  <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Setup Storage Size
                </p>
                <div className="w-full">
                  <Select>
                    <SelectTrigger className="w-full">
                      <SelectValue placeholder="Option" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="option 1">Option 1</SelectItem>
                      <SelectItem value="option 2">Option 2</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div> */}

              {/*               <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Invite Users
                </p>
                <div className="flex items-center gap-2 w-full">
                  <Input placeholder="Enter email" />
                  <Select>
                    <SelectTrigger className="w-48">
                      <SelectValue placeholder="Role" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="member">Member</SelectItem>
                      <SelectItem value="admin">Admin</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div> */}

              <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Select document sets
                </p>
                <div className="w-full">
                  <DocumentSets
                    documentSets={documentSets}
                    setSelectedDocumentSetIds={(documentSetIds) =>
                      setFieldValue("document_set_ids", documentSetIds)
                    }
                  />
                </div>
              </div>

              <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Select connectors
                </p>
                <div className="w-full">
                  <ConnectorEditor
                    allCCPairs={ccPairs}
                    selectedCCPairIds={values.cc_pair_ids}
                    setSetCCPairIds={(ccPairsIds) =>
                      setFieldValue("cc_pair_ids", ccPairsIds)
                    }
                  />
                </div>
              </div>

              <div className="flex justify-between pb-4 gap-2 flex-col lg:flex-row">
                <p className="whitespace-nowrap w-1/2 font-semibold">
                  Set Token Rate Limit
                </p>
                <div className="flex items-center gap-4 w-full">
                  <Input placeholder="Time Window (Hours)" type="number" />
                  <Input placeholder="Token Budget (Thousands)" type="number" />
                </div>
              </div>

              <div className="flex gap-2 pt-4 justify-end">
                <Button
                  disabled={isSubmitting}
                  className=""
                  onClick={onClose}
                  variant="ghost"
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={isSubmitting} className="">
                  {isUpdate ? "Update" : "Create"}
                </Button>
              </div>
            </div>
          </Form>
        )}
      </Formik>
    </div>
  );
};
