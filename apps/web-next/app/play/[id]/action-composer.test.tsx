// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ActionComposer } from "./action-composer";

afterEach(cleanup);

function Harness({ onSubmit }: { onSubmit: (value: string) => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  const [draft, setDraft] = useState("");
  return (
    <ActionComposer
      formRef={formRef}
      draft={draft}
      busy={false}
      completed={false}
      onDraftChange={setDraft}
      onSubmit={onSubmit}
    />
  );
}

describe("ActionComposer", () => {
  it("submits a player's exact draft with Enter", () => {
    const submit = vi.fn();
    render(<Harness onSubmit={submit} />);
    const textarea = screen.getByLabelText("描述你想做的事");

    fireEvent.change(textarea, { target: { value: "拒绝邀约，继续查档案" } });
    fireEvent.keyDown(textarea, { key: "Enter" });

    expect(submit).toHaveBeenCalledOnce();
    expect(submit).toHaveBeenCalledWith("拒绝邀约，继续查档案");
  });

  it("keeps Shift+Enter available for a new line", () => {
    const submit = vi.fn();
    render(<Harness onSubmit={submit} />);

    fireEvent.keyDown(screen.getByLabelText("描述你想做的事"), {
      key: "Enter",
      shiftKey: true,
    });

    expect(submit).not.toHaveBeenCalled();
  });

  it("disables action submission after the playthrough ends", () => {
    const formRef = { current: null };
    render(
      <ActionComposer
        formRef={formRef}
        draft="继续"
        busy={false}
        completed
        onDraftChange={() => undefined}
        onSubmit={() => undefined}
      />,
    );

    expect((screen.getByRole("button", { name: "发送行动" }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    expect((screen.getByLabelText("描述你想做的事") as HTMLTextAreaElement).disabled).toBe(true);
  });
});
