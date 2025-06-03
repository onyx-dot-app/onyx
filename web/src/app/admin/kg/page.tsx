"use client";

import CardSection from "@/components/admin/CardSection";
import { AdminPageTitle } from "@/components/admin/Title";
import {
  DatePickerField,
  FieldLabel,
  TextArrayField,
  TextFormField,
} from "@/components/Field";
import { BrainIcon } from "@/components/icons/icons";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { SwitchField } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Form, Formik, useFormikContext } from "formik";
import { useState } from "react";
import { FiSettings } from "react-icons/fi";
import * as Yup from "yup";
import { EntityType, Values } from "./interfaces";

function createDomainField(
  name: string,
  label: string,
  subtext: string,
  placeholder: string,
  minFields?: number
) {
  return function DomainFields({ disabled = false }: { disabled?: boolean }) {
    const { values } = useFormikContext<any>();

    return (
      <TextArrayField
        name={name}
        label={label}
        subtext={subtext}
        placeholder={placeholder}
        minFields={minFields}
        values={values}
        disabled={disabled}
      />
    );
  };
}

const VendorDomains = createDomainField(
  "vendorDomains",
  "Vendor Domains",
  "Domain names of your vendor.",
  "Domain",
  1
);

const IgnoreDomains = createDomainField(
  "ignoreDomains",
  "Ignore Domains",
  "Domain names to ignore.",
  "Domain"
);

function KGConfiguration() {
  const initialValues: Values = {
    enabled: false,
    vendor: "",
    vendorDomains: [""],
    ignoreDomains: [],
    coverageStart: null,
    coverageDays: null,
  };
  const validationSchema = Yup.object({
    enabled: Yup.boolean().required(),
    vendor: Yup.string().required("Vendor is required."),
    vendorDomains: Yup.array(
      Yup.string().required("Vendor Domain is required.")
    )
      .min(1)
      .required(),
    ignoreDomains: Yup.array(Yup.string().required("Ignore Domain is required"))
      .min(0)
      .required(),
    coverageStart: Yup.date().nullable(),
    coverageDays: Yup.number().positive().nullable(),
  });

  const [isEnabled, setIsEnabled] = useState(false);

  return (
    <Formik
      initialValues={initialValues}
      validationSchema={validationSchema}
      onSubmit={async (values) => {
        console.log(values);
      }}
    >
      {(props) => (
        <Form>
          <div className="flex flex-col gap-y-6 w-full">
            <div className="flex flex-col gap-y-1">
              <FieldLabel
                name="enabled"
                label="Enabled"
                subtext="Enable or disable Knowledge Graph."
              />
              <SwitchField
                name="enabled"
                className="flex flex-1"
                onCheckedChange={(state) => {
                  setIsEnabled(state);
                  if (!state) {
                    props.resetForm();
                  }
                }}
              />
            </div>
            <div
              className={`flex flex-col gap-y-6 ${
                isEnabled ? "" : "opacity-50"
              }`}
            >
              <TextFormField
                name="vendor"
                label="Vendor"
                subtext="The company which is providing this feature."
                className="flex flex-row flex-1 w-full"
                placeholder="My Company Inc."
                disabled={!isEnabled}
              />
              <VendorDomains disabled={!isEnabled} />
              <IgnoreDomains disabled={!isEnabled} />
              <DatePickerField
                name="coverageStart"
                label="Coverage Start"
                subtext="The start date of coverage for Knowledge Graph."
                disabled={!isEnabled}
              />
              <Button variant="submit" type="submit" disabled={!isEnabled}>
                Submit
              </Button>
            </div>
          </div>
        </Form>
      )}
    </Formik>
  );
}

function KGEntityType({}: {}) {
  const tableHeaders = ["Name", "Description", "Active"];
  const rows: EntityType[] = [
    {
      name: "ACCOUNT",
      description:
        "A company that could potentially be or is or was a customer of the vendor (Onyx). Note that Onyx can never be an ACCOUNT.",
      active: false,
    },
    {
      name: "CONCERN",
      description:
        "A concern that an  ACCOUNT has/had/ with implementing the VENDOR's (Onyx) solution. This is high-level, as shown by the allowed options.",
      active: false,
    },
    {
      name: "CONNECTOR",
      description:
        "A connection of Onyx/Danswer to a data source (generally an application or service) that the (potential customer) ACCOUNT uses, that the VENDOR Onyx can then connect to and ingest data from. This CANNOT be tools that Onyx uses directly to deliver its service.",
      active: false,
    },
    {
      name: "EMPLOYEE",
      description:
        "A person who speaks on behalf of 'our' company (the VENDOR Onyx or Danswer), NOT of another account. Therefore, employees of other companies are NOT included here. If in doubt, do NOT extract.",
      active: false,
    },
  ];

  return (
    <Table>
      <TableHeader>
        <TableRow>
          {tableHeaders.map((tableHeader) => (
            <TableHead key={tableHeader}>{tableHeader}</TableHead>
          ))}
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row, index) => (
          <TableRow key={index}>
            <TableCell>{row.name}</TableCell>
            <TableCell>{row.description}</TableCell>
            <TableCell>{row.active}</TableCell>
          </TableRow>
        ))}
        {/* <TableRow>{
          rows.map((row) => (
            <>
            </>
            <TableCell>{}</TableCell>
          ))
          }</TableRow> */}
      </TableBody>
    </Table>
  );
}

function Main() {
  const [configureModalShown, setConfigureModalShown] = useState(false);

  return (
    <div className="flex flex-col py-4 gap-y-8">
      <CardSection className="max-w-2xl text-text shadow-lg rounded-lg">
        <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
          Knowledge Graph Configuration
        </p>
        <div className="flex flex-col gap-y-6">
          <p className="text-text-600">
            Lorem ipsum dolor sit amet, consectetur adipiscing elit. Vestibulum
            imperdiet dolor ut nisl ultrices, a tempor massa cursus. Etiam a
            nisl et nisl venenatis scelerisque vel eu ex. Proin eu dolor vitae
            risus molestie sodales sed a risus.
          </p>
          <p className="text-text-600">
            Aliquam dignissim nisi quis venenatis venenatis. Suspendisse euismod
            purus eget ornare pharetra. Nullam aliquet enim ut lectus cursus,
            eget auctor nunc pulvinar. Maecenas at leo sit amet justo rutrum
            posuere sed at leo. Vestibulum efficitur leo vitae nunc eleifend
            egestas. Cras a congue ante, ac imperdiet libero.
          </p>
          <Button
            size="lg"
            icon={FiSettings}
            onClick={() => setConfigureModalShown(true)}
          >
            Configure Knowledge Graph
          </Button>
        </div>
      </CardSection>
      <div>
        <p className="text-2xl font-bold mb-4 text-text border-b border-b-border pb-2">
          Knowledge Graph Configuration
        </p>
        <KGEntityType />
      </div>
      {configureModalShown && (
        <Modal
          title="Configure Knowledge Graph"
          onOutsideClick={() => setConfigureModalShown(false)}
        >
          <KGConfiguration />
        </Modal>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Knowledge Graph"
        icon={<BrainIcon size={32} className="my-auto" />}
      />
      <Main />
    </div>
  );
}
