"use client";

import { useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/Field";

interface ReferralSourceSelectorProps {
  defaultValue?: string;
}

const ReferralSourceSelector: React.FC<ReferralSourceSelectorProps> = ({
  defaultValue,
}) => {
  const [referralSource, setReferralSource] = useState(defaultValue);

  const referralOptions = [
    { value: "search", label: "Search Engine (Google/Bing)" },
    { value: "friend", label: "Friend/Colleague" },
    { value: "linkedin", label: "LinkedIn" },
    { value: "twitter", label: "Twitter" },
    { value: "hackernews", label: "HackerNews" },
    { value: "reddit", label: "Reddit" },
    { value: "youtube", label: "YouTube" },
    { value: "podcast", label: "Podcast" },
    { value: "blog", label: "Article/Blog" },
    { value: "ads", label: "Advertisements" },
    { value: "other", label: "Other" },
  ];

  const handleChange = (value: string) => {
    setReferralSource(value);
    const cookies = require("js-cookie");
    cookies.set("referral_source", value, {
      expires: 365,
      path: "/",
      sameSite: "strict",
    });
  };

  return (
    <div className="w-full max-w-sm gap-y-2 flex flex-col mx-auto">
      <Label className="text-text-950" small={false}>
        How did you hear about us?
      </Label>
      <Select value={referralSource} onValueChange={handleChange}>
        <SelectTrigger
          id="referral-source"
          className="w-full border-background-300 rounded-md shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
        >
          <SelectValue placeholder="Select an option" />
        </SelectTrigger>
        <SelectContent className="max-h-60 overflow-y-auto">
          {referralOptions.map((option) => (
            <SelectItem
              key={option.value}
              value={option.value}
              className="py-2 px-3 hover:bg-indigo-100 cursor-pointer"
            >
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
};

export default ReferralSourceSelector;
