import { Check, SlidersHorizontal, Trash2, X } from "lucide-react";
import { useState } from "react";
import type { PlaythroughSettings } from "./game-types";

const descriptions: Record<string, string> = {
  concise: "节奏更快，适合频繁行动与移动端阅读。",
  standard: "情节、对话与细节保持均衡。",
  detailed: "增加环境、心理和人物反应描写。",
  long: "接近完整章节，生成时间和 token 消耗更高。",
};

export function GameSettingsRail({
  settings,
  onChange,
  onDelete,
  onClose,
}: {
  settings?: PlaythroughSettings;
  onChange: (value: PlaythroughSettings["narrative_length"]) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  return (
    <aside className="gameRail gameSettings" aria-label="本故事设置">
      <button className="gameRailClose" onClick={onClose} aria-label="关闭设置">
        <X size={16} />
      </button>
      <SlidersHorizontal size={22} aria-hidden="true" />
      <h2>本故事设置</h2>
      <p className="railCopy">这些选择只影响当前故事，从下一个回合开始生效。</p>

      <fieldset className="lengthPicker">
        <legend>每回合叙事长度</legend>
        {settings?.presets.map((preset) => {
          const selected = settings.narrative_length === preset.key;
          return (
            <button
              type="button"
              key={preset.key}
              className={selected ? "selected" : ""}
              aria-pressed={selected}
              onClick={() => onChange(preset.key)}
            >
              <span>
                <b>{preset.label}</b>
                <small>
                  约 {preset.min_chars}–{preset.max_chars} 字
                </small>
              </span>
              {selected && <Check size={16} aria-hidden="true" />}
              <em>{descriptions[preset.key]}</em>
            </button>
          );
        })}
      </fieldset>

      <section className="storyDangerZone">
        <h3>删除故事</h3>
        <p>故事会立即从书架移除，审计与恢复数据会按平台的数据保留策略处理。</p>
        {confirmingDelete ? (
          <div>
            <button className="button danger" onClick={onDelete}>
              确认删除
            </button>
            <button className="button ghost" onClick={() => setConfirmingDelete(false)}>
              取消
            </button>
          </div>
        ) : (
          <button className="button danger" onClick={() => setConfirmingDelete(true)}>
            <Trash2 size={16} /> 删除这个故事
          </button>
        )}
      </section>
    </aside>
  );
}
