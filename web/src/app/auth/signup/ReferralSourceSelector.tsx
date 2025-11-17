"use client";

import { useState } from "react";
import * as InputSelect from "@/refresh-components/inputs/InputSelect";
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
      <InputSelect.Root
        value={referralSource}
        onValueChange={handleChange}
        placeholder="Select an option"
        className="w-full border-background-300 !rounded-08 shadow-sm focus:border-indigo-500 focus:ring-indigo-500"
      >
        {referralOptions.map((option) => (
          <InputSelect.Item key={option.value} value={option.value}>
            {option.label}
          </InputSelect.Item>
        ))}
      </InputSelect.Root>
    </div>
  );
}
