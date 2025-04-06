import { useState } from "react";
import { Button } from "@/components/ui/button";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { FiUserPlus } from "react-icons/fi";
import CreateUserForm from "../CreateUserForm";

interface CreateUserButtonProps {
  setPopup: (spec: PopupSpec) => void;
}

const CreateUserButton = ({ setPopup }: CreateUserButtonProps) => {
  const [showForm, setShowForm] = useState(false);

  return (
    <>
      <Button className="my-auto w-fit" onClick={() => setShowForm(true)}>
        <div className="flex">
          <FiUserPlus className="my-auto mr-2" />
          Create User
        </div>
      </Button>

      {showForm && (
        <CreateUserForm
          onClose={() => setShowForm(false)}
          setPopup={setPopup}
        />
      )}
    </>
  );
};

export default CreateUserButton; 