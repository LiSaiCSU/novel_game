export type Entity = Record<string, unknown> & {
  key: string;
  name?: string;
  title?: string;
  description?: string;
};
export type Package = {
  manifest: {
    title: string;
    summary: string;
    rating: string;
    tags: string[];
    theme: Record<string, string>;
    assets: AssetReference[];
  };
  content: {
    world: Record<string, unknown>;
    scenarios: Entity[];
    locations: Entity[];
    characters: Entity[];
    facts: Entity[];
    endings: EndingDefinition[];
    plot_threads: Entity[];
    quests: Entity[];
    rules: Array<Record<string, unknown>>;
    narrative: Record<string, unknown>;
  };
  author_tests?: Array<Record<string, unknown>>;
};
export type Project = { id: string; title: string; revision: number; document: Package };
export type ProjectRevision = {
  revision: number;
  created_at: string;
  diagnostics: Diagnostic[];
  document: Package;
};
export type Diagnostic = { level: string; message: string };
export type Release = {
  id: string;
  version: string;
  visibility: string;
  status: string;
  checksum: string;
};
export type CreatedRelease = {
  id: string;
  checksum: string;
  status: string;
  share_token?: string | null;
};
export type AssetReference = {
  key: string;
  kind: "cover" | "avatar" | "background";
  path: string;
  alt: string;
};
export type Asset = AssetReference & {
  id: string;
  url: string;
  thumbnail_url?: string | null;
  width: number;
  height: number;
  byte_size: number;
  status: string;
};
export type EndingDefinition = {
  key: string;
  title: string;
  type: "romance" | "bond" | "independent" | "other";
  lead?: string | null;
  condition: unknown;
  requires_consent?: boolean;
  hidden_until_available?: boolean;
  priority?: number;
  epilogue: string;
};
export type AuthorAssertionResult = {
  path: string;
  op: string;
  passed: boolean;
  expected: unknown;
  actual: unknown;
  message: string;
};
export type AuthorTestResult = {
  key: string;
  name: string;
  passed: boolean;
  duration_ms: number;
  actions_run: number;
  assertions: AuthorAssertionResult[];
  error: string;
};
export type AuthorTestSuite = {
  passed: boolean;
  declared_tests: number;
  total: number;
  passed_count: number;
  failed_count: number;
  duration_ms: number;
  results: AuthorTestResult[];
};

export const tabs = [
  "概览",
  "世界与入口",
  "场景与地点",
  "人物",
  "事实与秘密",
  "任务与剧情线",
  "结局设计",
  "叙事风格",
  "规则",
  "玩法测试",
  "图片素材",
  "版本差异",
  "内容包",
  "发布中心",
];
export const clone = <T>(value: T): T => structuredClone(value);
