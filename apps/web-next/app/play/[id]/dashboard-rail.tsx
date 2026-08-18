import { X } from "lucide-react";
import { useState } from "react";
import { ClockStrip } from "./clock-strip";
import { displayLabel, metric, progressionMetric } from "./game-format";
import type { Dashboard, Ending, EndingStatus, Scene } from "./game-types";

type Props = {
  state?: Scene;
  dashboard?: Dashboard;
  endingStatus?: EndingStatus;
  completed: boolean;
  onConsent: (lead: string, decision: string) => void;
  onEnding: (ending: Ending) => void;
  onClose: () => void;
};

const tabs = ["人物", "关系", "任务", "背包", "结局"] as const;

export function DashboardRail({
  state,
  dashboard,
  endingStatus,
  completed,
  onConsent,
  onEnding,
  onClose,
}: Props) {
  const [activeTab, setActiveTab] = useState<(typeof tabs)[number]>("人物");

  return (
    <aside className="gameRail gameDashboard">
      <button className="gameRailClose" aria-label="关闭人物与状态" onClick={onClose}>
        <X size={18} aria-hidden="true" />
      </button>
      <div className="railTabs" role="tablist" aria-label="游戏状态">
        {tabs.map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            className={activeTab === tab ? "active" : ""}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === "人物" && (
        <section className="railPanel">
          <p className="eyebrow">主角</p>
          <h2>{state?.player?.name}</h2>
          {Object.entries(dashboard?.player.resources ?? {}).map(([key, value]) => (
            <div className="statRow" key={key}>
              <span>{displayLabel(dashboard?.labels.resources, key, "自定义资源")}</span>
              <b>{metric(value)}</b>
            </div>
          ))}
          {Object.entries(dashboard?.player.progressions ?? {}).map(([key, value]) => (
            <div className="statRow" key={key}>
              <span>{displayLabel(dashboard?.labels.progressions, key, "成长进度")}</span>
              <b>{progressionMetric(value, dashboard?.labels.progression_values)}</b>
            </div>
          ))}
          <h2 className="railSection">在场人物</h2>
          {state?.present_characters?.length ? (
            state.present_characters.map((character) => (
              <div className="statRow" key={character.name}>
                <span>{character.name}</span>
                <b>{displayLabel(undefined, character.title || character.faction || "", "")}</b>
              </div>
            ))
          ) : (
            <p className="studioHint">此刻没有其他人在场。</p>
          )}
        </section>
      )}

      {activeTab === "关系" && (
        <section className="railPanel">
          <p className="eyebrow">已建立的关系</p>
          {dashboard?.relationships.length ? (
            dashboard.relationships.map((relationship) => (
              <article className="relationCard" key={relationship.key}>
                <h2>{relationship.name}</h2>
                {Object.entries(relationship.dimensions)
                  .filter(([key]) =>
                    ["affection", "trust", "respect", "familiarity", "boundaries"].includes(key),
                  )
                  .map(([key, value]) => (
                    <div className="relationMetric" key={key}>
                      <span>{displayLabel(dashboard.labels.relationships, key, "关系变化")}</span>
                      <progress max="100" value={Math.max(0, Math.min(100, value))} />
                      <b>{value}</b>
                    </div>
                  ))}
                {relationship.tags.some((tag) => dashboard.labels.relationship_tags[tag]) && (
                  <p className="tagLine">
                    {relationship.tags
                      .map((tag) => dashboard.labels.relationship_tags[tag])
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                )}
              </article>
            ))
          ) : (
            <p className="studioHint">关系会从真实互动中逐渐形成。</p>
          )}
        </section>
      )}

      {activeTab === "任务" && (
        <section className="railPanel">
          {!!dashboard?.clocks.length && (
            <>
              <p className="eyebrow">正在走的钟</p>
              <ClockStrip clocks={dashboard.clocks} />
              {dashboard.clocks.some((clock) => clock.consequence) && (
                <div className="clockLegend">
                  {dashboard.clocks
                    .filter((clock) => clock.consequence)
                    .map((clock) => (
                      <p key={clock.key}>
                        <b>{clock.name}</b>满格后：{clock.consequence}
                      </p>
                    ))}
                </div>
              )}
              <h2 className="railSection">当前任务</h2>
            </>
          )}
          {!dashboard?.clocks.length && <p className="eyebrow">当前任务</p>}
          {dashboard?.quests.length ? (
            dashboard.quests.map((quest) => (
              <article className="railCard" key={quest.key}>
                <b>{quest.name}</b>
                <span>{displayLabel(dashboard.labels.statuses, quest.status, "状态已更新")}</span>
              </article>
            ))
          ) : (
            <p className="studioHint">当前没有公开任务。</p>
          )}
          <h2 className="railSection">剧情进展</h2>
          {dashboard?.threads.map((thread) => (
            <article className="railCard" key={thread.key}>
              <b>
                {thread.name}
                {thread.player_opened && <em className="ownThread">你开的线</em>}
              </b>
              <span>
                阶段 {thread.stage} ·{" "}
                {displayLabel(dashboard.labels.statuses, thread.status, "状态已更新")}
              </span>
              {thread.next_beat_hint && <small>{thread.next_beat_hint}</small>}
            </article>
          ))}
        </section>
      )}

      {activeTab === "背包" && (
        <section className="railPanel">
          <p className="eyebrow">持有物品</p>
          {dashboard?.inventory.length ? (
            dashboard.inventory.map((item) => (
              <div className="statRow" key={item.key}>
                <span>{displayLabel(undefined, item.name, "未命名物品")}</span>
                <b>× {item.quantity}</b>
              </div>
            ))
          ) : (
            <p className="studioHint">背包目前是空的。</p>
          )}
          <h2 className="railSection">能力</h2>
          {dashboard?.abilities.length ? (
            dashboard.abilities.map((ability) => (
              <div className="statRow" key={ability.key}>
                <span>{displayLabel(undefined, ability.name, "未命名能力")}</span>
                <b>{ability.mastery}</b>
              </div>
            ))
          ) : (
            <p className="studioHint">尚未掌握可显示的能力。</p>
          )}
        </section>
      )}

      {activeTab === "结局" && (
        <section className="railPanel endingPanel">
          <p className="eyebrow">关系意愿</p>
          <p className="studioHint">
            这是明确选择，不会由好感数值或模型替你决定。拒绝恋爱后，角色仍可发展友情与个人故事。
          </p>
          {Object.entries(endingStatus?.leads ?? {}).map(([lead, name]) => (
            <article className="consentCard" key={lead}>
              <b>{name}</b>
              <div className="consentButtons">
                <button
                  disabled={completed}
                  className={endingStatus?.consent[lead] === "accepted" ? "active" : ""}
                  onClick={() => onConsent(lead, "accepted")}
                >
                  愿意探索恋爱线
                </button>
                <button
                  disabled={completed}
                  className={endingStatus?.consent[lead] === "rejected" ? "active" : ""}
                  onClick={() => onConsent(lead, "rejected")}
                >
                  只做朋友
                </button>
                <button
                  disabled={completed}
                  className={endingStatus?.consent[lead] === "undecided" ? "active" : ""}
                  onClick={() => onConsent(lead, "undecided")}
                >
                  暂不决定
                </button>
              </div>
            </article>
          ))}
          <h2 className="railSection">可抵达的结局</h2>
          {endingStatus?.selected && (
            <article className="selectedEnding">
              <span>已经抵达</span>
              <b>{endingStatus.selected.title}</b>
            </article>
          )}
          {endingStatus?.endings
            .filter((ending) => ending.available)
            .map((ending) => (
              <button
                className="endingChoice"
                key={ending.key}
                disabled={completed}
                onClick={() => onEnding(ending)}
              >
                <span>
                  {ending.type === "romance" ? "恋爱" : ending.type === "bond" ? "羁绊" : "成长"}
                </span>
                <b>{ending.title}</b>
              </button>
            ))}
          {!completed && !endingStatus?.endings.some((ending) => ending.available) && (
            <p className="studioHint">
              继续推进主线、建立关系或完成个人目标，新的结局会在满足条件后出现。
            </p>
          )}
          {!!endingStatus?.hidden_count && (
            <p className="hiddenEnding">还有 {endingStatus.hidden_count} 个未揭示的可能</p>
          )}
        </section>
      )}
    </aside>
  );
}
