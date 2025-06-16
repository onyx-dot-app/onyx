import { GenerateContentRequest, GenerateContentResponse } from "@/lib/marketing/types";

const OPENAI_API_KEY = process.env.NEXT_PUBLIC_OPENAI_API_KEY || "your-openai-api-key-here";

export async function generateTextContent(prompt: string): Promise<string> {
  if (!OPENAI_API_KEY || OPENAI_API_KEY === "your-openai-api-key-here") {
    await new Promise(resolve => setTimeout(resolve, 1000));
    return `Generated marketing content for: "${prompt}"\n\nThis is a sample generated text that would normally come from OpenAI. The content would be tailored to your specific prompt and would include compelling marketing copy designed to engage your target audience.`;
  }

  try {
    const response = await fetch("https://api.openai.com/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: "gpt-4",
        messages: [
          {
            role: "system",
            content: "You are a professional marketing copywriter. Create compelling marketing content based on the user's prompt.",
          },
          {
            role: "user",
            content: prompt,
          },
        ],
        max_tokens: 500,
        temperature: 0.7,
      }),
    });

    if (!response.ok) {
      throw new Error(`OpenAI API error: ${response.statusText}`);
    }

    const data = await response.json();
    return data.choices[0]?.message?.content || "Failed to generate content";
  } catch (error) {
    console.error("Error generating text content:", error);
    throw new Error("Failed to generate text content");
  }
}

export async function generateImageContent(prompt: string): Promise<string> {
  if (!OPENAI_API_KEY || OPENAI_API_KEY === "your-openai-api-key-here") {
    await new Promise(resolve => setTimeout(resolve, 2000));
    return "https://via.placeholder.com/512x512/4F46E5/FFFFFF?text=Generated+Image";
  }

  try {
    const response = await fetch("https://api.openai.com/v1/images/generations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${OPENAI_API_KEY}`,
      },
      body: JSON.stringify({
        model: "dall-e-3",
        prompt: prompt,
        n: 1,
        size: "1024x1024",
        quality: "standard",
      }),
    });

    if (!response.ok) {
      throw new Error(`OpenAI API error: ${response.statusText}`);
    }

    const data = await response.json();
    return data.data[0]?.url || "Failed to generate image";
  } catch (error) {
    console.error("Error generating image content:", error);
    throw new Error("Failed to generate image content");
  }
}
