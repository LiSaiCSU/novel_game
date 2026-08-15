const labels: Record<string, string> = {
  active: "正常",
  disabled: "已停用",
  pending: "待处理",
  draft: "草稿",
  published: "已发布",
  archived: "已归档",
  completed: "已完成",
  approved: "已通过",
  rejected: "已拒绝",
  withdrawn: "已下架",
  investigating: "调查中",
  resolved: "已处理",
  dismissed: "已驳回",
  takedown: "已下架",
  queued: "等待处理",
  processing: "处理中",
  ready: "已就绪",
  failed: "失败",
  public: "公开",
  unlisted: "凭链接访问",
  private: "私密",
  player: "玩家",
  creator: "创作者",
  reviewer: "审核员",
  admin: "管理员",
  warning: "提醒",
  error: "错误",
  info: "信息",
  locations: "地点",
  characters: "人物",
  organizations: "组织",
  relationships: "关系",
  facts: "事实与知识",
  items: "物品",
  skills: "能力",
  quests: "任务",
  plot_threads: "剧情线",
  event_templates: "事件模板",
  schedules: "日程",
  endings: "结局",
  rules: "规则",
  assets: "素材",
  "zh-CN": "简体中文",
  "zh-TW": "繁体中文",
  "ja-JP": "日语",
  "moderation.decided": "完成版本审核",
  "moderation.appealed": "提交审核申诉",
  "report.decided": "完成举报处置",
  "release.created": "创建发布版本",
  "user.quota_changed": "调整用户额度",
  "user.roles_changed": "调整用户权限",
  "platform_llm.config_changed": "修改平台模型配置",
  "platform_llm.connection_test_failed": "平台模型连接测试失败",
  "platform_llm.connection_test_succeeded": "平台模型连接测试成功",
  "auth.login_failed": "登录失败",
  "auth.login_anomaly": "登录异常",
  "account.deleted": "删除账号数据",
};

export function interfaceLabel(value: string, fallback = "其他"): string {
  const key = value.trim();
  if (!key) return fallback;
  if (labels[key]) return labels[key];
  if (!/^[a-z][a-z0-9_.-]*$/i.test(key)) return key;
  return fallback;
}

export function roleLabels(roles: string[]): string {
  return roles.map((role) => interfaceLabel(role, "自定义角色")).join(" · ");
}
