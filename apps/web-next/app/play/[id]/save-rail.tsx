import { X } from "lucide-react";
import type { Save, Scene } from "./game-types";

type Props = {
  state?: Scene;
  saves: Save[];
  completed: boolean;
  onCreate: () => void;
  onLoad: (save: Save) => void;
  onDelete: (save: Save) => void;
  onClose: () => void;
};

export function SaveRail({ state, saves, completed, onCreate, onLoad, onDelete, onClose }: Props) {
  return (
    <aside className="gameRail gameSaveRail" aria-label="场景与存档">
      <button className="gameRailClose" aria-label="关闭场景与存档" onClick={onClose}>
        <X size={18} aria-hidden="true" />
      </button>
      <p className="eyebrow">当前场景</p>
      <h2>{state?.location?.name ?? "正在抵达…"}</h2>
      <p className="railCopy">{state?.location?.description}</p>
      <div className="statRow">
        <span>时间</span>
        <b>{state?.time?.label ?? "—"}</b>
      </div>
      <button className="button saveButton" disabled={completed} onClick={onCreate}>
        保存当前进度
      </button>
      <h2 className="railSection">存档</h2>
      {saves.length === 0 && (
        <p className="studioHint">还没有手动存档。每次行动本身也会写入历史。</p>
      )}
      {saves.map((save) => (
        <article className="saveItem" key={save.id}>
          <button onClick={() => onLoad(save)}>
            <b>{save.name}</b>
            <small>
              {save.location_name} · 回合 {save.turn_number}
            </small>
          </button>
          <button
            className="dangerLink"
            aria-label={`删除${save.name}`}
            onClick={() => onDelete(save)}
          >
            删除
          </button>
        </article>
      ))}
    </aside>
  );
}
