export type Character = { name: string; title?: string; faction?: string };

export type Scene = {
  time?: { label?: string };
  location?: { name?: string; description?: string };
  player?: { name?: string; health?: number[]; realm?: string };
  present_characters?: Character[];
  playthrough?: {
    status: string;
    ending_key?: string | null;
    ending_title?: string | null;
    settings?: PlaythroughSettings;
  };
};

export type NarrativeLengthPreset = {
  key: "concise" | "standard" | "detailed" | "long";
  label: string;
  min_chars: number;
  max_chars: number;
};

export type PlaythroughSettings = {
  narrative_length: NarrativeLengthPreset["key"];
  narrative_max_chars: number;
  presets: NarrativeLengthPreset[];
};

export type Choice = { label: string; hint?: string; action_type?: string };

export type History = { chapters: Array<{ input: string; text: string }>; choices: Choice[] };

export type Save = {
  id: string;
  name: string;
  turn_number: number;
  time_label: string;
  location_name: string;
  excerpt: string;
};

export type Relationship = {
  key: string;
  name: string;
  dimensions: Record<string, number>;
  tags: string[];
};

export type Dashboard = {
  player: {
    attributes: Record<string, unknown>;
    resources: Record<string, unknown>;
    progressions: Record<string, unknown>;
    properties: Record<string, unknown>;
  };
  inventory: Array<{ key: string; name: string; quantity: number }>;
  abilities: Array<{ key: string; name: string; mastery: number }>;
  relationships: Relationship[];
  quests: Array<{ key: string; name: string; status: string }>;
  threads: Array<{
    key: string;
    name: string;
    status: string;
    stage: number;
    next_beat_hint: string;
  }>;
  labels: {
    relationships: Record<string, string>;
    statuses: Record<string, string>;
    attributes: Record<string, string>;
    resources: Record<string, string>;
    progressions: Record<string, string>;
  };
};

export type Ending = {
  key: string;
  title: string;
  type: string;
  lead?: string;
  available: boolean;
  epilogue: string;
};

export type EndingStatus = {
  status: string;
  selected?: { key: string; title: string } | null;
  endings: Ending[];
  hidden_count: number;
  consent: Record<string, string>;
  leads: Record<string, string>;
};

export type Recap = {
  title: string;
  turn_number: number;
  updated_at: string;
  scene: { time: string; location: string };
  last_action: string;
  recent: Array<{ text: string; world_minute: number }>;
  objectives: Array<{ type: string; key: string; name: string; hint: string }>;
  suggestions: Choice[];
};

export const initialChoices: Choice[] = [
  {
    label: "我先仔细观察当前环境，留意容易错过的细节和他人的反应。",
    hint: "了解当前场景、人物状态与可互动线索",
    action_type: "OBSERVE",
  },
  {
    label: "我梳理已经掌握的线索与目标，判断现在最值得优先推进的事情。",
    hint: "避免盲目行动，让下一步围绕当前目标展开",
    action_type: "QUERY_QUESTS",
  },
  {
    label: "我主动和在场的人打招呼，从对方的态度里了解这里的情况。",
    hint: "开启对话，同时留意对方愿意透露和刻意回避的信息",
    action_type: "TALK",
  },
];
