// @vitest-environment jsdom

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EntityList, JsonEditor } from "./editor-controls";

describe("creator editor controls", () => {
  it("keeps an invalid JSON draft without overwriting the document", () => {
    const apply = vi.fn();
    render(<JsonEditor label="规则 JSON" value={{ enabled: true }} onApply={apply} />);

    const editor = screen.getByLabelText("规则 JSON");
    fireEvent.change(editor, { target: { value: '{"enabled":' } });
    fireEvent.blur(editor);
    expect(apply).not.toHaveBeenCalled();

    fireEvent.change(editor, { target: { value: '{"enabled":false}' } });
    fireEvent.blur(editor);
    expect(apply).toHaveBeenCalledWith({ enabled: false });
  });

  it("creates a stable key for the next author entity", () => {
    const change = vi.fn();
    render(<EntityList kind="事实" items={[]} fields={[]} onChange={change} />);

    fireEvent.click(screen.getByRole("button", { name: "添加事实" }));

    expect(change).toHaveBeenCalledWith([{ key: "fact_1", statement: "新事实", sensitivity: 0 }]);
  });
});
