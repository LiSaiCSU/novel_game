// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GameSettingsRail } from "./game-settings-rail";

afterEach(cleanup);

describe("GameSettingsRail", () => {
  it("explains and changes the generation range for this story", () => {
    const onChange = vi.fn();
    render(
      <GameSettingsRail
        settings={{
          narrative_length: "standard",
          narrative_max_chars: 1600,
          presets: [
            { key: "standard", label: "标准", min_chars: 1360, max_chars: 1600 },
            { key: "detailed", label: "丰富", min_chars: 2040, max_chars: 2400 },
          ],
        }}
        onChange={onChange}
        onDelete={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("约 1360–1600 字")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /丰富/ }));
    expect(onChange).toHaveBeenCalledWith("detailed");
  });

  it("requires an explicit second click before deleting", () => {
    const onDelete = vi.fn();
    render(
      <GameSettingsRail
        settings={{ narrative_length: "standard", narrative_max_chars: 1600, presets: [] }}
        onChange={vi.fn()}
        onDelete={onDelete}
        onClose={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "删除这个故事" }));
    expect(onDelete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "确认删除" }));
    expect(onDelete).toHaveBeenCalledOnce();
  });
});
