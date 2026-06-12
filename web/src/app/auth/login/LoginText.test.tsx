import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import LoginText from "./LoginText";

const messages = {
  auth: { title: "欢迎使用 Glomi AI", subtitle: "你的 AI 工作平台" },
};

describe("LoginText", () => {
  it("renders the Chinese welcome copy", () => {
    render(
      <NextIntlClientProvider locale="zh" messages={messages}>
        <LoginText />
      </NextIntlClientProvider>
    );
    expect(screen.getByText("欢迎使用 Glomi AI")).toBeInTheDocument();
    expect(screen.getByText("你的 AI 工作平台")).toBeInTheDocument();
  });
});
