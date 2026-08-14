"use client";

import { ErrorState, RetryButton } from "@/components/ui/async-state";

export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="routeState">
      <ErrorState
        title="页面没有顺利打开"
        description="你的数据没有丢失。可以重新加载，或稍后回到这里继续。"
        action={<RetryButton onClick={reset} />}
      />
    </div>
  );
}
