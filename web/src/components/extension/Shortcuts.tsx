import { useState, useEffect } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Shortcut } from "@/app/chat/nrf/interfaces";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { PencilIcon, PlusIcon } from "lucide-react";
import Image from "next/image";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { Modal } from "../Modal";
import { QuestionMarkIcon } from "../icons/icons";

export const validateUrl = (input: string) => {
  try {
    new URL(input);
    return true;
  } catch {
    return false;
  }
};

export const ShortCut = ({
  shortCut,
  onEdit,
}: {
  shortCut: Shortcut;
  onEdit: (shortcut: Shortcut) => void;
}) => {
  const [faviconError, setFaviconError] = useState(false);

  return (
    <div className="w-24 h-24 flex-none rounded-xl shadow-lg relative group transition-all duration-300 ease-in-out hover:scale-105 bg-white/10 backdrop-blur-sm">
      <button
        onClick={(e) => {
          e.stopPropagation();
          onEdit(shortCut);
        }}
        className="absolute top-1 right-1 p-1 bg-white/20 rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-200"
      >
        <PencilIcon className="w-3 h-3 text-white" />
      </button>
      <div
        onClick={() => window.open(shortCut.url, "_blank")}
        className="w-full h-full flex flex-col items-center justify-center cursor-pointer"
      >
        <div className="w-8 h-8 mb-2 relative">
          {shortCut.favicon && !faviconError ? (
            <Image
              src={shortCut.favicon}
              alt={shortCut.name}
              width={40}
              height={40}
              className="rounded-sm"
              onError={() => setFaviconError(true)}
            />
          ) : (
            <QuestionMarkIcon size={32} className="text-white w-full h-full" />
          )}
        </div>
        <h1 className="text-white w-full text-center font-semibold text-sm truncate px-2">
          {shortCut.name}
        </h1>
      </div>
    </div>
  );
};

export const AddShortCut = ({
  openShortCutModal,
}: {
  openShortCutModal: () => void;
}) => {
  return (
    <button
      onClick={openShortCutModal}
      className="w-24 h-24 flex-none rounded-xl bg-white/10 hover:bg-white/20 backdrop-blur-sm transition-all duration-300 ease-in-out flex flex-col items-center justify-center"
    >
      <PlusIcon className="w-8 h-8 text-white mb-2" />
      <h1 className="text-white text-xs font-medium">New Bookmark</h1>
    </button>
  );
};

export const NewShortCutModal = ({
  isOpen,
  onClose,
  onAdd,
  editingShortcut,
  onDelete,
  setPopup,
}: {
  isOpen: boolean;
  onClose: () => void;
  onDelete: (shortcut: Shortcut) => void;
  onAdd: (shortcut: Shortcut) => void;
  editingShortcut?: Shortcut | null;
  setPopup: (popup: PopupSpec) => void;
}) => {
  const [name, setName] = useState(editingShortcut?.name || "");
  const [url, setUrl] = useState(editingShortcut?.url || "");
  const [faviconError, setFaviconError] = useState(false);
  const [isValidUrl, setIsValidUrl] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (isValidUrl) {
      const faviconUrl = `https://www.google.com/s2/favicons?domain=${
        new URL(url).hostname
      }&sz=64`;
      onAdd({ name, url, favicon: faviconUrl });
      onClose();
    } else {
      console.error("Invalid URL submitted");
      setPopup({
        type: "error",
        message: "Please enter a valid URL",
      });
    }
  };

  const handleUrlChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const newUrl = e.target.value;
    setUrl(newUrl);
    setIsValidUrl(validateUrl(newUrl));
    setFaviconError(false);
  };

  useEffect(() => {
    setIsValidUrl(validateUrl(url));
  }, [url]);

  const faviconUrl = isValidUrl
    ? `https://www.google.com/s2/favicons?domain=${new URL(url).hostname}&sz=64`
    : "";

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-[95%] sm:max-w-[425px] bg-neutral-900 border-none text-white">
        <DialogHeader>
          <DialogTitle>
            {editingShortcut ? "Edit Shortcut" : "Add New Shortcut"}
          </DialogTitle>
          <DialogDescription>
            {editingShortcut
              ? "Modify your existing shortcut."
              : "Create a new shortcut for quick access to your favorite websites."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="w-full space-y-6">
          <div className="space-y-4 w-full">
            <div className="flex flex-col space-y-2">
              <Label
                htmlFor="name"
                className="text-sm font-medium text-neutral-300"
              >
                Name
              </Label>
              <Input
                id="name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full bg-neutral-800 border-neutral-700 text-white"
                placeholder="Enter shortcut name"
              />
            </div>
            <div className="flex flex-col space-y-2">
              <Label
                htmlFor="url"
                className="text-sm font-medium text-neutral-300"
              >
                URL
              </Label>
              <Input
                id="url"
                value={url}
                onChange={handleUrlChange}
                className={`bg-neutral-800 border-neutral-700 text-white ${
                  !isValidUrl && url ? "border-red-500" : ""
                }`}
                placeholder="https://example.com"
              />
              {!isValidUrl && url && (
                <p className="text-red-500 text-sm">Please enter a valid URL</p>
              )}
            </div>
            <div className="flex items-center space-x-2">
              <Label className="text-sm font-medium text-neutral-300">
                Favicon Preview:
              </Label>
              <div className="w-8 h-8 relative flex items-center justify-center">
                {isValidUrl && !faviconError ? (
                  <Image
                    src={faviconUrl}
                    alt="Favicon"
                    width={32}
                    height={32}
                    className="w-full h-full rounded-sm"
                    onError={() => setFaviconError(true)}
                  />
                ) : (
                  <QuestionMarkIcon size={32} className="w-full h-full" />
                )}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="submit"
              className="bg-blue-600 hover:bg-blue-700 text-white"
              disabled={!isValidUrl || !name}
            >
              {editingShortcut ? "Save Changes" : "Add Shortcut"}
            </Button>
            {editingShortcut && (
              <Button
                type="button"
                variant="destructive"
                onClick={() => onDelete(editingShortcut)}
              >
                Delete
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
};

export const MaxShortcutsReachedModal = ({
  onClose,
}: {
  onClose: () => void;
}) => {
  return (
    <Modal
      width="max-w-md"
      title="Maximum Shortcuts Reached"
      onOutsideClick={onClose}
    >
      <div className="flex flex-col gap-4">
        <p className="text-left text-neutral-900">
          You&apos;ve reached the maximum limit of 8 shortcuts. To add a new
          shortcut, please remove an existing one.
        </p>
        <Button onClick={onClose}>Close</Button>
      </div>
    </Modal>
  );
};
