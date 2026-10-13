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

export type OptionKind = "ask" | "press" | "comfort" | "bluff";

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

export type CaseResult = {
  ending: string;
  solved: boolean;
  title: string;
  text: string;
  epilogues: string[];
  accused: string;
  culprit_correct: boolean;
  weapon_correct: boolean;
  motive_correct: boolean;
  pillars: Pillar[];
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
    title: string;
    tagline: string;
    setting: string;
    estimated_minutes: string;
    minutes_total: number;
    suspects: number;
    goal: string;
    victim: string;
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
  accusation: {
    suspects: Array<{ key: string; name: string; role: string }>;
    weapons: Array<{ key: string; label: string }>;
    motives: Array<{ key: string; label: string }>;
    max_evidence: number;
    pillars: string[];
  };
  result: CaseResult | null;
  interpreted_as?: string;
};

export type MoveBody = {
  kind: "begin" | "talk" | "examine" | "option" | "present" | "think" | "accuse";
  target?: string;
  evidence?: string;
  culprit?: string;
  weapon?: string;
  motive?: string;
  exhibits?: string[];
};
