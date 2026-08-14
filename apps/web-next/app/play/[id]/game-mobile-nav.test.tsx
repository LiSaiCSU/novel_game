// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { GameMobileNavigation, type MobileView } from "./game-mobile-nav";

afterEach(cleanup);

function Harness() {
  const [view, setView] = useState<MobileView>("story");
  return <GameMobileNavigation value={view} onChange={setView} />;
}

describe("GameMobileNavigation", () => {
  it("keeps status, save and story settings reachable on narrow screens", () => {
    render(<Harness />);

    expect(screen.getByRole("button", { name: "故事" }).getAttribute("aria-current")).toBe("page");
    fireEvent.click(screen.getByRole("button", { name: "人物与状态" }));
    expect(screen.getByRole("button", { name: "人物与状态" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(screen.getByRole("button", { name: "故事" }).getAttribute("aria-current")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "场景与存档" }));
    expect(screen.getByRole("button", { name: "场景与存档" }).getAttribute("aria-current")).toBe(
      "page",
    );

    fireEvent.click(screen.getByRole("button", { name: "设置" }));
    expect(screen.getByRole("button", { name: "设置" }).getAttribute("aria-current")).toBe("page");
  });
});
