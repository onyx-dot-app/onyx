import { Formik, Form } from "formik";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import { SvgEdit } from "@opal/icons";
import { BooleanFormField, TextArrayField } from "@/components/Field";
import { toast } from "@/hooks/useToast";
import { updateConnectorConnectorConfig } from "@/lib/connector";
import { DEFAULT_GITLAB_CODE_FILE_PATTERNS } from "@/lib/connectors/connectors";

interface GitlabFileTypesFormValues {
  include_code_files: boolean;
  code_file_patterns: string[];
}

interface EditGitlabFileTypesModalProps {
  ccPairId: number;
  initialIncludeCodeFiles: boolean;
  initialCodeFilePatterns: string[];
  onClose: () => void;
  onSaved: () => void;
}

export default function EditGitlabFileTypesModal({
  ccPairId,
  initialIncludeCodeFiles,
  initialCodeFilePatterns,
  onClose,
  onSaved,
}: EditGitlabFileTypesModalProps) {
  const initialValues: GitlabFileTypesFormValues = {
    include_code_files: initialIncludeCodeFiles,
    code_file_patterns: initialCodeFilePatterns,
  };

  const handleSubmit = async (values: GitlabFileTypesFormValues) => {
    const normalizedPatterns = values.code_file_patterns
      .map((pattern) => pattern.trim())
      .filter((pattern) => pattern.length > 0);

    // Only write fields the user actually changed. A connector created
    // before these options existed may omit include_code_files and rely on
    // the backend's env default — persisting an untouched checkbox would
    // silently override that default.
    const configUpdates: Record<string, unknown> = {};
    if (values.include_code_files !== initialIncludeCodeFiles) {
      configUpdates.include_code_files = values.include_code_files;
    }
    if (
      JSON.stringify(normalizedPatterns) !==
      JSON.stringify(initialCodeFilePatterns)
    ) {
      configUpdates.code_file_patterns = normalizedPatterns;
    }
    if (Object.keys(configUpdates).length === 0) {
      onClose();
      return;
    }

    const response = await updateConnectorConnectorConfig(
      ccPairId,
      configUpdates
    );

    if (!response.ok) {
      toast.error(`Failed to update file types: ${await response.text()}`);
      return;
    }

    toast.success(
      "File type settings updated. A re-index has been scheduled so the new filter applies to the whole repository."
    );
    onSaved();
    onClose();
  };

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgEdit}
          title="Edit Indexed File Types"
          onClose={onClose}
        />
        <Modal.Body>
          <Formik initialValues={initialValues} onSubmit={handleSubmit}>
            {({ isSubmitting, values, setFieldValue }) => (
              <Form className="w-full">
                <BooleanFormField
                  name="include_code_files"
                  label="Include code files"
                  subtext="Clone the repository and index its files. Subsequent syncs only re-index files changed since the last sync."
                />

                {values.include_code_files && (
                  <div className="pt-4">
                    <TextArrayField
                      name="code_file_patterns"
                      label="Code File Patterns"
                      subtext="Glob patterns for files to index. Patterns without a '/' match the filename anywhere (e.g. *.py, Makefile, Dockerfile); patterns with a '/' match the path (e.g. src/*.py). Leave empty to use the built-in defaults, or click 'Use defaults' to start from the built-in list."
                      placeholder="*.py"
                      values={values}
                    />
                    <div className="pt-2">
                      <Button
                        type="button"
                        prominence="tertiary"
                        size="sm"
                        onClick={() =>
                          setFieldValue(
                            "code_file_patterns",
                            DEFAULT_GITLAB_CODE_FILE_PATTERNS
                          )
                        }
                      >
                        Use defaults
                      </Button>
                    </div>
                  </div>
                )}

                <Modal.Footer>
                  <Disabled disabled={isSubmitting}>
                    <Button type="submit">
                      {isSubmitting ? "Updating..." : "Save file types"}
                    </Button>
                  </Disabled>
                </Modal.Footer>
              </Form>
            )}
          </Formik>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
