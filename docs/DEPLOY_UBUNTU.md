# novelgame.online 一键部署

本方案面向一台已经安装 Docker Engine、Docker Compose Plugin 和 Git 的 Ubuntu 服务器。
服务器运行 Next.js、FastAPI、Worker、PostgreSQL、Redis、MinIO 和 ClamAV；可选择独占服务器的
Caddy，或与现有站点共存的宿主机 Nginx。公网只开放 `80/443`，其余服务位于 Docker 私有网络。

## 0. 上线前准备

1. 将 `novelgame.online` 的 A 记录指向服务器公网 IPv4；使用 IPv6 时同时正确配置 AAAA。
2. 防火墙只开放 SSH、HTTP 和 HTTPS，即 `22/80/443`。
3. 准备一个真实 SMTP 账号，否则新用户无法收到验证和重置邮件。
4. 准备 Sentry DSN。后端的 production 校验会拒绝没有错误聚合的配置。
5. 按需准备平台 LLM 的 provider、模型和 API Key；不配置时可选择 `null`，玩家仍可使用 BYOK。
6. 建议至少预留 8 GB 内存；ClamAV、构建过程、PostgreSQL 和应用会同时占用内存。

如果旧版独占 `80/443`，可先在旧部署目录备份并停止旧服务。不要使用 `down -v`，它会删除旧卷：

```bash
docker compose down
```

新编排固定使用 `novegame-v2` 项目名和独立数据卷，不会主动删除或复用旧版数据。

## 1. 首次部署

```bash
git clone <你的 GitHub 仓库地址> /opt/novegame
cd /opt/novegame
sudo bash scripts/deploy-production.sh
```

如果服务器上的 Nginx 还承载其他域名，首次运行改用：

```bash
sudo env REVERSE_PROXY_MODE=nginx WEB_HOST_PORT=3100 API_HOST_PORT=8100 \
  bash scripts/deploy-production.sh
```

脚本会新增独立的 `novelgame.online` 虚拟主机并调用 Certbot，不会停止或覆盖其他域名配置。

首次执行会交互式询问：

- 域名，默认 `novelgame.online`；
- HTTPS 证书通知邮箱；
- 反向代理模式：独占服务器选 `caddy`，服务器已有 Nginx 站点时选 `nginx`；
- Web 容器绑定的本机回环端口，默认 `3100`；
- Sentry DSN；
- SMTP 地址、账号、密码和发件人；
- 可选的平台模型 provider、模型名称、API Key 与兼容接口地址。

数据库、Redis、MinIO、会话签名、BYOK 加密和指标访问密钥自动随机生成。配置保存在
`/etc/novegame/novegame.env`，权限为 `0600`，不会写入仓库。

部署脚本会依次：

1. 校验生产配置；
2. 构建带 Git 提交标签的 API 和 Web 镜像；
3. 启动 PostgreSQL、Redis、MinIO、ClamAV；
4. 创建 `NOSUPERUSER NOBYPASSRLS` 应用数据库角色；
5. 运行 Alembic；
6. 启动 API、Worker 和 Web，并配置 Caddy 或宿主机 Nginx；
7. 等待内部依赖与 `https://novelgame.online/api/ready` 全部通过。

成功时最后会显示：

```text
Deployment succeeded: https://novelgame.online
```

## 2. 创建首位管理员

先在网站完成注册和邮箱验证，再在服务器执行：

```bash
cd /opt/novegame
sudo bash scripts/promote-admin.sh 你的邮箱@example.com
```

重新登录后即可执行管理员操作。命令同时授予 `admin` 和 `reviewer`，不会修改密码或跳过邮箱
验证。MFA 默认是可选的；需要强制管理员二次验证时，将生产环境中的
`ADMIN_MFA_REQUIRED` 改为 `true` 并重新部署。

## 3. 日常更新

```bash
cd /opt/novegame
git pull --ff-only && sudo bash scripts/deploy-production.sh
```

已有数据库时，部署脚本会在迁移前自动将 PostgreSQL、MinIO 素材和部署密钥备份到：

```text
/var/backups/novegame/<UTC时间>/
```

本机自动保留 14 天。生产环境还应把备份同步到另一台机器或对象存储，并定期实测恢复。

## 4. 回到上一版应用

```bash
cd /opt/novegame
sudo bash scripts/rollback-production.sh
```

该命令切回上一组 API/Web 镜像，不逆转数据库迁移。如果旧代码与新数据库不兼容，必须恢复
同一次部署前生成的 PostgreSQL 和素材备份。

## 5. 常用排查命令

```bash
cd /opt/novegame

sudo docker compose \
  --env-file /etc/novegame/novegame.env \
  -f compose.prod.yaml ps

sudo docker compose \
  --env-file /etc/novegame/novegame.env \
  -f compose.prod.yaml logs --tail=200 api worker web caddy

curl https://novelgame.online/api/health
curl https://novelgame.online/api/ready
```

如果 HTTPS 没有签发，优先检查：

- DNS 是否已经指向这台服务器；
- 云防火墙和 Ubuntu 防火墙是否开放 80/443；
- 旧版 Nginx、Apache 或容器是否仍占用 80/443；
- 所选 Caddy 或 Nginx 的日志是否报告 ACME、证书或域名错误。

## 6. 修改生产配置

```bash
sudoedit /etc/novegame/novegame.env
cd /opt/novegame
sudo bash scripts/deploy-production.sh
```

不要随意旋转 `AUTH_PEPPER`，否则现有登录会话失效；不要在没有迁移方案时旋转
`CREDENTIAL_ENCRYPTION_KEY`，否则已有 BYOK 和 MFA 密文无法解密。修改平台模型价格时同时更新
`LLM_PRICE_TABLE`，避免成本台账继续使用过期价格。

## 7. 旧版数据

一键部署不会自动导入旧匿名世界、旧 SQLite 或未知结构的旧 PostgreSQL 数据。新部署使用独立卷，
因此旧数据会保留在原目录或原 Docker 卷中。确认新站稳定并完成所需数据导出前，不要删除旧目录、
旧卷或旧备份。
