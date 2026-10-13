import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CaseRun, MoveBody } from "./case-types";

function friendly(error: unknown): string {
  return (error as Error).message || "操作没有完成";
}

export function useCaseRun(id: string) {
  const [run, setRun] = useState<CaseRun>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<"" | "move" | "say">("");
  const [error, setError] = useState("");

  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    api<CaseRun>(`/case-runs/${id}`)
      .then((next) => {
        if (!active) return;
        setRun(next);
        setError("");
      })
      .catch((exception) => active && setError(friendly(exception)))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id, reloadKey]);

  const reload = useCallback(() => {
    setLoading(true);
    setReloadKey((key) => key + 1);
  }, []);

  const move = useCallback(
    async (body: MoveBody) => {
      setBusy("move");
      setError("");
      try {
        const next = await api<CaseRun>(`/case-runs/${id}/moves`, {
          method: "POST",
          body: JSON.stringify(body),
        });
        setRun(next);
        return next;
      } catch (exception) {
        setError(friendly(exception));
        return undefined;
      } finally {
        setBusy("");
      }
    },
    [id],
  );

  const say = useCallback(
    async (character: string, text: string) => {
      setBusy("say");
      setError("");
      try {
        const next = await api<CaseRun>(`/case-runs/${id}/say`, {
          method: "POST",
          body: JSON.stringify({ character, text }),
        });
        setRun(next);
        return true;
      } catch (exception) {
        setError(friendly(exception));
        return false;
      } finally {
        setBusy("");
      }
    },
    [id],
  );

  return { run, loading, busy, error, setError, reload, move, say };
}
