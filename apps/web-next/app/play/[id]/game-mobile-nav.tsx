import { BookOpenText, Bookmark, PanelRight, Settings2 } from "lucide-react";

export const mobileViews = [
  { key: "saves", label: "场景与存档", icon: Bookmark },
  { key: "story", label: "故事", icon: BookOpenText },
  { key: "status", label: "人物与状态", icon: PanelRight },
  { key: "settings", label: "设置", icon: Settings2 },
] as const;

export type MobileView = (typeof mobileViews)[number]["key"];

export function GameMobileNavigation({
  value,
  onChange,
}: {
  value: MobileView;
  onChange: (value: MobileView) => void;
}) {
  return (
    <nav className="gameMobileNav" aria-label="游戏面板">
      {mobileViews.map(({ key, label, icon: Icon }) => (
        <button
          type="button"
          key={key}
          className={value === key ? "active" : ""}
          aria-current={value === key ? "page" : undefined}
          onClick={() => onChange(key)}
        >
          <Icon size={18} />
          <span>{label}</span>
        </button>
      ))}
    </nav>
  );
}
