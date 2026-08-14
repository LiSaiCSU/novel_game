import { LoadingState } from "@/components/ui/async-state";

export default function Loading() {
  return (
    <div className="routeState">
      <LoadingState label="正在打开叙事世界" />
    </div>
  );
}
