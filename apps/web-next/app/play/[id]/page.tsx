"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { ErrorState, LoadingState, RetryButton } from "@/components/ui/async-state";
import { DashboardRail } from "./dashboard-rail";
import { GameMobileNavigation, type MobileView } from "./game-mobile-nav";
import type { Ending, Save } from "./game-types";
import { SaveRail } from "./save-rail";
import { StoryPanel } from "./story-panel";
import { GameSettingsRail } from "./game-settings-rail";
import { usePlaythrough } from "./use-playthrough";

export default function Game() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const game = usePlaythrough(id);
  const [mobileView, setMobileView] = useState<MobileView>("story");

  function run(operation: Promise<void>) {
    operation.catch(game.reportError);
  }

  if (game.loading && !game.state) {
    return (
      <div className="gameLoading">
        <LoadingState label="正在恢复世界状态与你的上一段故事" />
      </div>
    );
  }

  if (!game.state) {
    return (
      <div className="gameLoading">
        <ErrorState
          title="这一段故事暂时无法打开"
          description={game.error || "存档可能已失效，或当前账号没有访问权限。"}
          action={<RetryButton onClick={() => void game.reload()} />}
        />
      </div>
    );
  }

  return (
    <div className="gameShell" data-mobile-view={mobileView}>
      {mobileView !== "story" && (
        <button
          className="gamePanelBackdrop"
          aria-label="关闭游戏面板"
          onClick={() => setMobileView("story")}
        />
      )}
      <SaveRail
        state={game.state}
        saves={game.saves}
        completed={game.completed}
        onCreate={() => run(game.createSave())}
        onLoad={(save: Save) => run(game.loadSave(save))}
        onDelete={(save: Save) => run(game.deleteSave(save))}
        onClose={() => setMobileView("story")}
      />
      <StoryPanel
        state={game.state}
        chapters={game.chapters}
        current={game.current}
        choices={game.choices}
        dashboard={game.dashboard}
        beat={game.beat}
        draft={game.draft}
        recap={game.recap}
        showRecap={game.showRecap}
        progress={game.progress}
        error={game.error}
        qualityWarning={game.qualityWarning}
        busy={game.busy}
        completed={game.completed}
        onHideRecap={() => game.setShowRecap(false)}
        onDraftChange={game.setDraft}
        onAct={(text) => run(game.act(text))}
        onOpenSaves={() => setMobileView("saves")}
        onOpenStatus={() => setMobileView("status")}
        onOpenSettings={() => setMobileView("settings")}
      />
      <DashboardRail
        state={game.state}
        dashboard={game.dashboard}
        endingStatus={game.endingStatus}
        completed={game.completed}
        onConsent={(lead, decision) => run(game.setConsent(lead, decision))}
        onEnding={(ending: Ending) => run(game.chooseEnding(ending))}
        onClose={() => setMobileView("story")}
      />
      <GameSettingsRail
        settings={game.settings}
        onChange={(value) => run(game.updateSettings(value))}
        onDelete={() =>
          run(
            game.deleteStory().then(() => {
              router.replace("/play");
              router.refresh();
            }),
          )
        }
        onClose={() => setMobileView("story")}
      />
      <GameMobileNavigation value={mobileView} onChange={setMobileView} />
    </div>
  );
}
