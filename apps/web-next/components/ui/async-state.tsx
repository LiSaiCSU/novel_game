import { AlertCircle, Inbox, LoaderCircle, RotateCcw } from "lucide-react";
import type { ReactNode } from "react";

type StateProps = {
  title: string;
  description?: string;
  action?: ReactNode;
  compact?: boolean;
};

export function EmptyState({ title, description, action, compact = false }: StateProps) {
  return (
    <section className={`statePanel ${compact ? "compact" : ""}`}>
      <span className="stateIcon" aria-hidden="true">
        <Inbox />
      </span>
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="stateAction">{action}</div>}
    </section>
  );
}

export function ErrorState({
  title = "这里暂时没有加载成功",
  description,
  action,
  compact = false,
}: Partial<StateProps>) {
  return (
    <section className={`statePanel errorState ${compact ? "compact" : ""}`} role="alert">
      <span className="stateIcon" aria-hidden="true">
        <AlertCircle />
      </span>
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="stateAction">{action}</div>}
    </section>
  );
}

export function RetryButton({
  onClick,
  label = "重新加载",
}: {
  onClick: () => void;
  label?: string;
}) {
  return (
    <button className="button secondary" type="button" onClick={onClick}>
      <RotateCcw size={16} />
      {label}
    </button>
  );
}

export function LoadingState({ label = "正在准备内容" }: { label?: string }) {
  return (
    <div className="loadingState" role="status">
      <LoaderCircle aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function CardSkeletons({ count = 3 }: { count?: number }) {
  return (
    <div className="cardGrid" role="status" aria-label="正在加载">
      {Array.from({ length: count }, (_, index) => (
        <article className="workCard skeletonCard" key={index} aria-hidden="true">
          <div className="skeleton skeletonCover" />
          <div className="workBody">
            <div className="skeleton skeletonMeta" />
            <div className="skeleton skeletonTitle" />
            <div className="skeleton skeletonLine" />
            <div className="skeleton skeletonLine short" />
          </div>
        </article>
      ))}
    </div>
  );
}
