# 回合计费与运营操作说明

## 已实现的安全边界

- `wallet_holds` 在平台模型推理前锁定有限的叙点预授权；锁定本身不会改变余额。
- 回合成功后，系统以 `usage_ledger` 中有效、非降级模型调用的真实微单位成本结算；失败、降级或安全拒绝会释放预授权且不扣点。
- 预授权快照保存每叙点换算率，运营人员在长回合执行期间改价不会追溯改变该玩家的费用。实际成本高于预留上限时，系统封顶扣点并产生 `capped` 指标，便于排查定价而非静默超扣。
- 同一个请求幂等键只对应一个预授权和一笔结算账目：已完成回合可安全重放；已释放的失败请求必须使用新幂等键再次尝试。
- 管理员余额扣减同样扣除进行中预授权后校验可用余额，不能把已为玩家回合锁定的权益挪作人工调账。

## 管理员操作

`GET /api/v1/admin/commerce/summary` 提供账本、进行中预授权与订单状态的聚合视图。管理员可通过 `PUT /api/v1/admin/commerce/billing-policy` 启停平台模型回合结算并调整叙点名称、换算率、单回合预留上限与超时时间。

策略写入要求管理员角色、近期 MFA、CSRF 凭证和至少三字符的变更理由；每次变更均写入审计日志。玩家可从 `GET /api/v1/commerce/wallet` 或 `/api/v1/commerce/billing-policy` 在行动前看到余额、已预留余额和当前计费策略。BYOK 绝不经过平台钱包。

## 运营赠点活动

管理员使用 `GET/POST /api/v1/admin/commerce/campaigns` 创建和查看赠点活动，并用 `PUT /api/v1/admin/commerce/campaigns/{campaign_id}/status` 启用、暂停或结束。所有写入都需要管理员角色、近期 MFA、CSRF 凭证与至少三字符理由，分别写入 `commerce.campaign_created` 或 `commerce.campaign_status_changed` 审计事件；活动不提供删除接口，结束后的活动也不能重新启用。

活动必须指定代码、名称、正整数赠点、含时区的开始/结束时间，且结束时间晚于开始时间。可以设置总领取上限。玩家通过 `GET /api/v1/commerce/campaigns` 只会看见当前生效且尚有余量的活动；`POST /api/v1/commerce/campaigns/{code}/redeem` 会限流并锁定活动行，校验有效期/状态/上限后，以 `campaign:{campaign_id}:{user_id}` 作为钱包幂等键新增一笔 `grant` 账目。重试会返回已存在结果，不会重复增加余额；成功领取会写入 `commerce.campaign_redeemed` 审计事件。

当前版本的活动面向所有已验证账号，并非现金、折现或可转让权益。指定人群、批量发放、预算审批、反欺诈规则和批量回滚账目应在后续运营体系中独立实现，不能以直接更新余额替代。

## 监控与告警

Prometheus 提供以下低基数指标：

- `narrative_http_requests_total`
- `narrative_http_request_duration_seconds_bucket`（可计算 P95/P99）
- `narrative_http_requests_in_flight`
- `narrative_billing_turn_reservations_total`
- `narrative_billing_turn_settlements_total`
- `narrative_billing_credits_settled_total`
- `narrative_llm_calls_total`
- `narrative_llm_tokens_total`
- `narrative_llm_cost_microunits_total`

标签绝不包含用户、故事、提示词、订单或支付凭据。建议对 P95 回合 API 时延、`capped` 结算、预授权不足突然上升、模型调用失败率以及每日模型成本阈值建立告警。

## 尚未启用的支付能力

支付订单快照已经存在，但真实充值渠道保持关闭。启用支付适配器前，经营方必须确认收款主体、服务地区、币种税务、退款/拒付政策、未成年人规则、已签名 webhook 验证和人工对账流程。支付成功的唯一入账路径应为：服务端验签事件 → 幂等订单结算 → 新增钱包账目与审计日志；浏览器跳转或客户端回传永远不能作为到账依据。

## 套餐目录与价格披露

`GET /api/v1/commerce/catalog` 公开返回已启用套餐、ISO 4217 货币与最小货币单位价格。该接口明确返回 `checkout_live: false`，不要求登录，也不会创建订单、预留权益或发起扣款。

管理员用 `GET/PUT /api/v1/admin/commerce/catalog` 预设最多 24 个套餐。写操作要求管理员角色、有效 MFA、CSRF 凭证与变更理由，并写入 `commerce.catalog_changed` 审计事件。套餐代码不可重复，价格和叙点必须是正整数；停用套餐仅对管理员可见，方便审核后再发布。

在真实支付接入前，玩家余额中心与公开定价页只展示价格，不显示“立即购买”按钮。开始接入前必须先由经营方确认收款主体、首发地区与货币、税务/发票、退款和拒付流程、未成年人规则、条款披露以及服务端签名 webhook 的验收负责人。
