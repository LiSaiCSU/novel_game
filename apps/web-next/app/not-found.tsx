import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { EmptyState } from "@/components/ui/async-state";

export default function NotFound() {
  return (
    <div className="routeState">
      <EmptyState
        title="这一页还没有故事"
        description="链接可能已经失效，或作品仍处于未公开状态。"
        action={
          <Link className="button primary" href="/library">
            <ArrowLeft size={16} />
            返回作品库
          </Link>
        }
      />
    </div>
  );
}
