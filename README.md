# AI 工具使用场景目录站（零投资自动版）

按「使用场景」整理的 AI 工具导航站。**完全零服务器、零域名费**，靠 GitHub Actions 每天自动抓取新工具、调用 LLM 生成介绍、提交回仓库，由 Cloudflare Pages 免费发布。变现靠联盟链接（淘宝联盟/京东联盟/SaaS 联盟）。

## 成本
- 托管：**Cloudflare Pages 免费**（无限带宽，国内访问最快的免费静态托管）
- 调度：**GitHub Actions 免费**（2000 分钟/月，每日跑一次足够）
- LLM：**DeepSeek**，约 ¥0.1/百万 token，目录站每月几毛钱（也可先不填 key 跑通流程）
- 域名：先用 `xxx.pages.dev` 免费子域；想正经做 SEO 再买域名（¥几十/年）+ 备案

## 一键部署步骤（约 10 分钟，不花一分钱）
1. **建 GitHub 仓库**：把本目录（`static-site/`）内容推上去。
2. **拿到 DeepSeek key**：去 https://platform.deepseek.com → API keys → 创建，复制 `sk-...`。
3. **仓库里加 Secret**：GitHub 仓库 → Settings → Secrets → New repository secret，名字 `DEEPSEEK_API_KEY`，值填 key。（也可本地把 `config.example.json` 复制为 `config.json` 填入 key，但别提交 config.json）
4. **连 Cloudflare Pages**：登录 https://pages.cloudflare.com → 连接 Git 仓库 → 框架选 **None** → 构建命令留空 → 输出目录填 `public` → 部署。
5. 完成。此后每天北京时间 09:00 自动跑，新工具自动进站点；你只需偶尔去 Cloudflare/联盟后台看收益。

## 本地试运行
```bash
pip install -r requirements.txt
cp config.example.json config.json   # 填入 deepseek_api_key（可留空先跑通）
python generate.py                   # 生成 public/index.html + public/tools/*.html
```
打开 `public/index.html` 即可预览。无 key 时条目仅含官网链接，流程照样跑通。

## 如何变现
- 在 `config.json` 的 `affiliate_links` 填入你自己的**淘宝联盟/京东联盟**推广链接（免费注册）。
- 很多 AI 工具（SaaS）有自带联盟计划（20–50% 复购佣金），把你的专属链接填进对应工具页。
- 站点流量起来后，可加「付费收录/置顶」「站内 Newsletter 订阅」。

## 与 WP 版的关系
本目录另含 `../`（上级）的 WordPress 插件版，适合**已验证变现、想做严肃 SEO 长尾**时升级使用。本零投资版是前置验证 MVP。

## 自动运行逻辑
```
GitHub Actions 每天定时
  → 抓 Hacker News 近期 AI 工具 + 读 seed_tools.json
  → 对每个新工具调 DeepSeek 生成「定位/使用场景/人群/优缺点/标签」
  → 渲染为静态 HTML，写入 public/
  → 提交回仓库 → Cloudflare Pages 自动发布
你：偶尔审核内容 + 查看联盟收益
```
