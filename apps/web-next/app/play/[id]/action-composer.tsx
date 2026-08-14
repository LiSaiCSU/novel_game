import type { FormEvent, KeyboardEvent, RefObject } from "react";

type Props = {
  formRef: RefObject<HTMLFormElement | null>;
  draft: string;
  busy: boolean;
  completed: boolean;
  onDraftChange: (value: string) => void;
  onSubmit: (value: string) => void;
};

export function ActionComposer({
  formRef,
  draft,
  busy,
  completed,
  onDraftChange,
  onSubmit,
}: Props) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSubmit(draft);
  }

  function keyboardSubmit(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      formRef.current?.requestSubmit();
    }
  }

  return (
    <form className="composer" ref={formRef} onSubmit={submit}>
      <textarea
        className="textarea"
        value={draft}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={keyboardSubmit}
        aria-label="描述你想做的事"
        placeholder={
          completed
            ? "本局已经抵达结局；读取较早存档可继续行动。"
            : "选择建议，或用自己的话行动。Ctrl / ⌘ + Enter 发送。"
        }
        disabled={completed}
      />
      <button className="button primary" disabled={completed || busy || !draft.trim()}>
        行动
      </button>
    </form>
  );
}
