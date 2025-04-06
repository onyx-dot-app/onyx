import { useState } from "react";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { Modal } from "@/components/Modal";
import { Button } from "@/components/ui/button";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { TextFormField } from "@/components/admin/connectors/Field";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { basicSignup } from "@/lib/user";
import { mutate } from "swr";

interface CreateUserFormProps {
  onClose: () => void;
  setPopup: (spec: PopupSpec) => void;
}

const validationSchema = Yup.object().shape({
  email: Yup.string()
    .email("Invalid email address")
    .required("Email is required"),
  password: Yup.string()
    .min(8, "Password must be at least 8 characters")
    .required("Password is required"),
  role: Yup.string().required("Role is required"),
});

const CreateUserForm = ({ onClose, setPopup }: CreateUserFormProps) => {
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handleSubmit = async (values: {
    email: string;
    password: string;
    role: string;
  }) => {
    setIsSubmitting(true);
    try {
      const response = await basicSignup(values.email, values.password);

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || "Failed to create user");
      }

      const data = await response.json();
      setPopup({
        message: `Successfully created user ${data.email} with role ${values.role}`,
        type: "success",
      });
      onClose();
      // Refresh the users list
      mutate("/api/users");
    } catch (error) {
      setPopup({
        message: error instanceof Error ? error.message : "Failed to create user",
        type: "error",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal title="Create New User" onOutsideClick={onClose}>
      <Formik
        initialValues={{
          email: "",
          password: "",
          role: UserRole.BASIC,
        }}
        validationSchema={validationSchema}
        onSubmit={handleSubmit}
      >
        {({ errors, touched, setFieldValue, values }) => (
          <Form className="flex flex-col gap-y-4">
            <TextFormField
              name="email"
              label="Email"
              placeholder="user@example.com"
              autoCompleteDisabled={true}
            />
            <TextFormField
              name="password"
              label="Password"
              type="password"
              placeholder="Enter password"
              autoCompleteDisabled={true}
            />
            <div className="flex flex-col gap-y-2">
              <label htmlFor="role" className="text-sm font-medium">
                Role
              </label>
              <Select
                value={values.role}
                onValueChange={(value) => setFieldValue("role", value)}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a role" />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(USER_ROLE_LABELS)
                    .filter(([role]) => [UserRole.ADMIN, UserRole.BASIC, UserRole.DEMO].includes(role as UserRole))
                    .map(([role, label]) => (
                      <SelectItem key={role} value={role}>
                        {label}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {touched.role && errors.role && (
                <div className="text-error text-sm">{errors.role}</div>
              )}
            </div>
            <div className="flex justify-end mt-4">
              <Button
                type="submit"
                disabled={isSubmitting}
                className="w-full"
              >
                {isSubmitting ? "Creating..." : "Create User"}
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </Modal>
  );
};

export default CreateUserForm; 