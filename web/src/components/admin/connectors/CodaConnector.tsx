"use client";

import { useState } from "react";
import { Formik, Form, Field, ErrorMessage } from "formik";
import * as Yup from "yup";
import { FiEye, FiEyeOff, FiExternalLink } from "react-icons/fi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface CodaConnectorProps {
  onSubmit: (values: { coda_api_token: string }) => void;
  isSubmitting?: boolean;
  initialValues?: { coda_api_token?: string };
}

const validationSchema = Yup.object({
  coda_api_token: Yup.string()
    .required("Coda API token is required")
    .min(10, "API token seems too short")
    .matches(
      /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i,
      "API token must be in UUID format (e.g., 12345678-1234-1234-1234-123456789abc)"
    ),
});

export default function CodaConnector({ 
  onSubmit, 
  isSubmitting = false, 
  initialValues = {} 
}: CodaConnectorProps) {
  const [showToken, setShowToken] = useState(false);

  return (
    <Card className="w-full max-w-2xl mx-auto">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <span>Coda Configuration</span>
          <a
            href="https://coda.io"
            target="_blank"
            rel="noopener noreferrer"
            className="text-blue-500 hover:text-blue-700"
          >
            <FiExternalLink size={18} />
          </a>
        </CardTitle>
        <CardDescription>
          Connect your Coda workspace to index documents and pages for search
        </CardDescription>
      </CardHeader>
      
      <CardContent>
        <Alert className="mb-6">
          <AlertDescription>
            <div className="space-y-2">
              <p className="font-medium">To get your Coda API token:</p>
              <ol className="list-decimal list-inside space-y-1 text-sm">
                <li>Go to your <a href="https://coda.io/account#apiSettings" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">Coda Account Settings</a></li>
                <li>Scroll down to the "API" section</li>
                <li>Click "Generate API token"</li>
                <li>Give it a name like "Onyx Connector"</li>
                <li>Copy the token and paste it below</li>
              </ol>
            </div>
          </AlertDescription>
        </Alert>

        <Formik
          initialValues={{
            coda_api_token: initialValues.coda_api_token || "",
          }}
          validationSchema={validationSchema}
          onSubmit={(values) => {
            onSubmit(values);
          }}
        >
          {({ errors, touched, values }) => (
            <Form className="space-y-4">
              <div>
                <Label htmlFor="coda_api_token">
                  Coda API Token <span className="text-red-500">*</span>
                </Label>
                <div className="relative mt-1">
                  <Field
                    as={Input}
                    type={showToken ? "text" : "password"}
                    id="coda_api_token"
                    name="coda_api_token"
                    placeholder="001a1ae7-17d6-44af-b6d3-314b7e95ec13"
                    className={`pr-10 ${
                      errors.coda_api_token && touched.coda_api_token
                        ? "border-red-500 focus:border-red-500"
                        : ""
                    }`}
                  />
                  <button
                    type="button"
                    className="absolute right-3 top-1/2 transform -translate-y-1/2 text-gray-400 hover:text-gray-600"
                    onClick={() => setShowToken(!showToken)}
                  >
                    {showToken ? <FiEyeOff size={16} /> : <FiEye size={16} />}
                  </button>
                </div>
                <ErrorMessage
                  name="coda_api_token"
                  component="div"
                  className="text-red-500 text-sm mt-1"
                />
                <p className="text-sm text-gray-500 mt-1">
                  Your API token should look like: 001a1ae7-17d6-44af-b6d3-314b7e95ec13
                </p>
              </div>

              <div className="bg-gray-50 p-4 rounded-md">
                <h4 className="font-medium text-sm mb-2">What will be indexed:</h4>
                <ul className="text-sm text-gray-600 space-y-1">
                  <li>• All documents you have access to</li>
                  <li>• All pages within those documents</li>
                  <li>• Document metadata (titles, authors, timestamps)</li>
                  <li>• Content will be kept in sync automatically</li>
                </ul>
              </div>

              <div className="flex justify-end">
                <Button
                  type="submit"
                  disabled={isSubmitting || !values.coda_api_token}
                  className="min-w-[120px]"
                >
                  {isSubmitting ? "Connecting..." : "Connect Coda"}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
      </CardContent>
    </Card>
  );
}