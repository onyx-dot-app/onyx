import React, { Dispatch, forwardRef, SetStateAction } from "react";
import { Formik, Form, FormikProps } from "formik";
import * as Yup from "yup";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/admin/connectors/Field";

interface AdvancedFormPageProps {
  formikProps: FormikProps<{
    indexingStart: string | null;
    pruneFreq: number;
    refreshFreq: number;
  }>;
}

const AdvancedFormPage = forwardRef<FormikProps<any>, AdvancedFormPageProps>(
  ({ formikProps }, ref) => {
    const { indexingStart, refreshFreq, pruneFreq } = formikProps.values;

    return (
      <div className="py-4 rounded-lg max-w-2xl mx-auto">
        <h2 className="text-2xl font-bold mb-4 text-text-800">
          Advanced Configuration
        </h2>

        <Form>
          <div key="prune_freq">
            <NumberInput
              description={`
                  Checks all documents against the source to delete those that no longer exist.
                  Note: This process checks every document, so be cautious when increasing frequency.
                  Default is 30 days.
                  Enter 0 to disable pruning for this connector.
                `}
              value={pruneFreq}
              label="Prune Frequency (days)"
              name="pruneFreq"
            />
          </div>

          <div key="refresh_freq">
            <NumberInput
              description="This is how frequently we pull new documents from the source (in minutes). If you input 0, we will never pull new documents for this connector."
              value={refreshFreq}
              label="Refresh Frequency (minutes)"
              name="refreshFreq"
            />
          </div>

          <div key="indexing_start">
            <TextFormField
              type="date"
              subtext="Documents prior to this date will not be pulled in"
              optional
              label="Indexing Start Date"
              name="indexingStart"
              value={indexingStart!}
            />
          </div>
        </Form>
      </div>
    );
  }
);

AdvancedFormPage.displayName = "AdvancedFormPage";
export default AdvancedFormPage;
