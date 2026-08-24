// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "@/lib/api";
import { LandingPage } from "./landing-page";

vi.mock("@/lib/api", () => ({ api: vi.fn() }));

const apiMock = vi.mocked(api);

afterEach(() => {
  cleanup();
  apiMock.mockReset();
});

describe("landing page", () => {
  it("gives an anonymous visitor a clear registration and discovery path", async () => {
    apiMock.mockRejectedValueOnce(new Error("not signed in"));
    render(<LandingPage />);

    expect(screen.getByRole("link", { name: /免费开始一段故事/ }).getAttribute("href")).toBe(
      "/register",
    );
    expect(screen.getByRole("link", { name: /先浏览作品/ }).getAttribute("href")).toBe(
      "/library",
    );
    expect(await screen.findByText("权益和价格公开可查")).toBeTruthy();
  });
});
