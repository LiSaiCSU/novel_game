import { ArrowUp } from "lucide-react";
import type { ChangeEvent, FormEvent, KeyboardEvent, RefObject } from "react";

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
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      formRef.current?.requestSubmit();
    }
  }

  function changeDraft(event: ChangeEvent<HTMLTextAreaElement>) {
    onDraftChange(event.target.value);
    event.target.style.height = "auto";
    event.target.style.height = `${Math.min(event.target.scrollHeight, 144)}px`;
  }

  return (
    <form className="composer" ref={formRef} onSubmit={submit}>
      <textarea
        className="textarea"
        rows={1}
        value={draft}
        onChange={changeDraft}
        onKeyDown={keyboardSubmit}
        aria-label="描述你想做的事"
        placeholder={completed ? "本局已经抵达结局；读取较早存档可继续行动。" : "描述你想做的事……"}
        disabled={completed}
      />
      <button
        className="composerSend"
        aria-label={busy ? "正在回应" : "发送行动"}
        title="发送行动"
        disabled={completed || busy || !draft.trim()}
      >
        <ArrowUp size={19} aria-hidden="true" />
      </button>
      <small className="composerHint">Enter 发送 · Shift + Enter 换行</small>
    </form>
  );
}
