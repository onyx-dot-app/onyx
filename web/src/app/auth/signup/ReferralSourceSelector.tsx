"use client";

import { useState } from "react";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Label } from "@/components/Field";

interface ReferralSourceSelectorProps {
  defaultValue?: string;
}

export default function ReferralSourceSelector({
  defaultValue,
}: ReferralSourceSelectorProps) {
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
    <div className="w-full gap-y-2 flex flex-col">
      <Label className="text-text-950" small={false}>
        How did you hear about us?
      </Label>
      <InputSelect
        value={referralSource}
        onValueChange={handleChange}
        className="w-full border-background-300 !rounded-08 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
      >
        <InputSelect.Trigger placeholder="Select an option" />

        <InputSelect.Content>
          {referralOptions.map((option) => (
            <InputSelect.Item key={option.value} value={option.value}>
              {option.label}
            </InputSelect.Item>
          ))}
        </InputSelect.Content>
      </InputSelect>
    </div>
  );
}
