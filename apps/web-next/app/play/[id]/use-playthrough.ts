"use client";

import { useCallback, useEffect, useState } from "react";
import { api, streamApi } from "@/lib/api";
import { formatChapters } from "./game-format";
import {
  type Choice,
  type Dashboard,
  type Ending,
  type EndingStatus,
  type History,
  initialChoices,
  type Recap,
  type Save,
  type Scene,
} from "./game-types";

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求没有完成";
}

export function usePlaythrough(id: string) {
  const [state, setState] = useState<Scene>();
  const [chapters, setChapters] = useState<string[]>([]);
  const [current, setCurrent] = useState<{ input: string; narrative: string }>();
  const [choices, setChoices] = useState<Choice[]>(initialChoices);
  const [beat, setBeat] = useState("");
  const [draft, setDraft] = useState("");
  const [saves, setSaves] = useState<Save[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard>();
  const [endingStatus, setEndingStatus] = useState<EndingStatus>();
  const [recap, setRecap] = useState<Recap>();
  const [showRecap, setShowRecap] = useState(true);
  const [progress, setProgress] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const [nextState, history, saved, nextDashboard, endings] = await Promise.all([
      api<Scene>(`/playthroughs/${id}/state`),
      api<History>(`/playthroughs/${id}/history`),
      api<Save[]>(`/playthroughs/${id}/saves`),
      api<Dashboard>(`/playthroughs/${id}/dashboard`),
      api<EndingStatus>(`/playthroughs/${id}/endings`),
    ]);
    setState(nextState);
    setChapters(formatChapters(history));
    if (history.choices.length) setChoices(history.choices);
    setSaves(saved);
    setDashboard(nextDashboard);
    setEndingStatus(endings);
  }, [id]);

  useEffect(() => {
    Promise.all([
      api<Scene>(`/playthroughs/${id}/state`),
      api<History>(`/playthroughs/${id}/history`),
      api<Save[]>(`/playthroughs/${id}/saves`),
      api<Dashboard>(`/playthroughs/${id}/dashboard`),
      api<EndingStatus>(`/playthroughs/${id}/endings`),
      api<Recap>(`/playthroughs/${id}/recap`),
    ])
      .then(([nextState, history, saved, nextDashboard, endings, returnRecap]) => {
        setState(nextState);
        setChapters(formatChapters(history));
        if (history.choices.length) setChoices(history.choices);
        setSaves(saved);
        setDashboard(nextDashboard);
        setEndingStatus(endings);
        setRecap(returnRecap);
        if (returnRecap.suggestions.length) setChoices(returnRecap.suggestions);
      })
      .catch((loadError: unknown) => setError(errorMessage(loadError)))
      .finally(() => setLoading(false));
  }, [id]);

  async function reload(): Promise<void> {
    setLoading(true);
    setError("");
    try {
      await refresh();
      const returnRecap = await api<Recap>(`/playthroughs/${id}/recap`);
      setRecap(returnRecap);
      if (returnRecap.suggestions.length) setChoices(returnRecap.suggestions);
    } catch (loadError) {
      setError(errorMessage(loadError));
    } finally {
      setLoading(false);
    }
  }

  async function act(text: string): Promise<void> {
    const action = text.trim();
    if (!action || busy) return;
    setBusy(true);
    setError("");
    setBeat("");
    setCurrent({ input: action, narrative: "" });
    setProgress("正在理解你的意图");
    setDraft("");
    let narrative = "";
    try {
      await streamApi(
        `/playthroughs/${id}/actions/stream`,
        { text: action, idempotency_key: crypto.randomUUID() },
        (streamEvent, payload) => {
          if (streamEvent === "narrative") {
            narrative += String(payload.delta ?? "");
            setCurrent({ input: action, narrative });
          } else if (streamEvent === "progress") {
            const summary = String(payload.summary ?? "");
            setProgress(
              summary ? `世界变化：${summary}` : `世界已推进 ${String(payload.minutes ?? 0)} 分钟`,
            );
          } else if (streamEvent === "state") {
            setState(payload.visible_updates as Scene);
            const nextChoices = (payload.choices as Choice[] | undefined) ?? [];
            if (nextChoices.length) setChoices(nextChoices);
            const nextBeat = payload.beat as { question?: string; options?: Choice[] } | null;
            setBeat(nextBeat?.question ?? "");
            if (nextBeat?.options?.length) setChoices(nextBeat.options);
          } else if (streamEvent === "error") {
            throw new Error(String(payload.message ?? "行动失败"));
          }
        },
      );
      setCurrent(undefined);
      await refresh();
    } catch (actionError) {
      setError(errorMessage(actionError));
      setDraft(action);
    } finally {
      setProgress("");
      setBusy(false);
    }
  }

  async function createSave(): Promise<void> {
    const name = `第 ${chapters.length} 章 · ${state?.time?.label ?? "当前进度"}`;
    await api(`/playthroughs/${id}/saves`, {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    setSaves(await api<Save[]>(`/playthroughs/${id}/saves`));
  }

  async function loadSave(save: Save): Promise<void> {
    if (!window.confirm(`回到“${save.name}”？该存档之后的进度会被覆盖。`)) return;
    await api(`/playthroughs/${id}/saves/${save.id}/load`, { method: "POST" });
    await refresh();
  }

  async function deleteSave(save: Save): Promise<void> {
    if (!window.confirm(`删除存档“${save.name}”？`)) return;
    await api(`/playthroughs/${id}/saves/${save.id}`, { method: "DELETE" });
    setSaves((items) => items.filter((item) => item.id !== save.id));
  }

  async function setConsent(lead: string, decision: string): Promise<void> {
    await api(`/playthroughs/${id}/relationships/${lead}/consent`, {
      method: "PUT",
      body: JSON.stringify({ decision }),
    });
    setEndingStatus(await api<EndingStatus>(`/playthroughs/${id}/endings`));
    setDashboard(await api<Dashboard>(`/playthroughs/${id}/dashboard`));
  }

  async function chooseEnding(ending: Ending): Promise<void> {
    if (!window.confirm(`以“${ending.title}”结束这一局？之后仍可读取较早的手动存档。`)) {
      return;
    }
    await api(`/playthroughs/${id}/ending`, {
      method: "POST",
      body: JSON.stringify({ ending_key: ending.key }),
    });
    await refresh();
  }

  function reportError(operationError: unknown): void {
    setError(errorMessage(operationError));
  }

  return {
    state,
    chapters,
    current,
    choices,
    beat,
    draft,
    setDraft,
    saves,
    dashboard,
    endingStatus,
    recap,
    showRecap,
    setShowRecap,
    progress,
    error,
    busy,
    loading,
    completed: state?.playthrough?.status === "completed",
    act,
    createSave,
    loadSave,
    deleteSave,
    setConsent,
    chooseEnding,
    reload,
    reportError,
  };
}
