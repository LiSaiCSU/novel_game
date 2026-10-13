export type EvidenceKind = "physical" | "document" | "testimony" | "observation";

export const evidenceKindLabel: Record<EvidenceKind, string> = {
  physical: "物证",
  document: "文书",
  testimony: "证词",
  observation: "观察",
};

export type Evidence = {
  key: string;
  name: string;
  kind: EvidenceKind;
  description: string;
};

export type Statement = { key: string; text: string; broken: boolean };

export type OptionKind = "ask" | "press" | "comfort" | "bluff" | "trade" | "act";

export type CaseOption = { key: string; kind: OptionKind; label: string };

export type CaseCharacter = {
  key: string;
  name: string;
  role: string;
  description: string;
  suspect: boolean;
  met: boolean;
  silent: boolean;
  patience: number;
  patience_max: number;
  /** Scheme mode: how far this person leans toward the player; null when not tracked. */
  stance: number | null;
  statements: Statement[];
  options: CaseOption[];
};

export type Spot = { key: string; label: string; examined: boolean };

export type CaseLocation = {
  key: string;
  name: string;
  description: string;
  spots: Spot[];
};

export type LogKind =
  | "narration"
  | "npc"
  | "player"
  | "evidence"
  | "break"
  | "fail"
  | "event"
  | "note"
  | "system"
  | "verdict";

export type LogEntry = {
  id: number;
  kind: LogKind;
  text: string;
  speaker: string | null;
  evidence: string | null;
  minutes_left: number;
};

export type Page = { title: string; body: string };

export type Pillar = { key: string; label: string; met: boolean };

export type CaseMode = "deduction" | "scheme";

export type Grade = "S" | "A" | "B" | "C" | "F";

export type CaseResult = {
  mode: CaseMode;
  ending: string;
  solved: boolean;
  title: string;
  text: string;
  epilogues: string[];
  // Deduction
  accused?: string;
  culprit_correct?: boolean;
  weapon_correct?: boolean;
  motive_correct?: boolean;
  pillars?: Pillar[];
  // Scheme
  route?: string;
  label?: string;
  grade?: Grade;
  stars?: Pillar[];
  minutes_left: number;
  lies_broken: number;
  lies_total: number;
  evidence_found: number;
  evidence_total: number;
};

export type CaseStatus = "briefing" | "active" | "deadline" | "closed";

export type CaseRun = {
  id: string;
  case: {
    key: string;
    mode: CaseMode;
    title: string;
    tagline: string;
    setting: string;
    estimated_minutes: string;
    minutes_total: number;
    suspects: number;
    routes_total: number;
    goal: string;
    victim: string;
    clock_label: string;
    action_minutes: number;
    briefing: Page[];
    rules: Page[];
  };
  status: CaseStatus;
  minutes_left: number;
  current: string | null;
  characters: CaseCharacter[];
  locations: CaseLocation[];
  evidence: Evidence[];
  log: LogEntry[];
  progress: {
    lies_broken: number;
    lies_total: number;
    evidence_found: number;
    evidence_total: number;
  };
  accusation: Accusation | null;
  scheme: {
    stars: string[];
    routes: RouteCard[];
  } | null;
  result: CaseResult | null;
  interpreted_as?: string;
};

export type Accusation = {
  suspects: Array<{ key: string; name: string; role: string }>;
  weapons: Array<{ key: string; label: string }>;
  motives: Array<{ key: string; label: string }>;
  max_evidence: number;
  pillars: string[];
};

/** A way to win. Its name stays hidden until the player has found it once. */
export type RouteCard = {
  key: string | null;
  title: string | null;
  label: string | null;
  teaser: string;
  discovered: boolean;
};

export const stanceLabel = (stance: number): string =>
  stance <= -2
    ? "敌对"
    : stance === -1
      ? "戒备"
      : stance === 0
        ? "观望"
        : stance === 1
          ? "动摇"
          : "站你这边";

export type MoveBody = {
  kind: "begin" | "talk" | "examine" | "option" | "present" | "think" | "accuse";
  target?: string;
  evidence?: string;
  culprit?: string;
  weapon?: string;
  motive?: string;
  exhibits?: string[];
};
