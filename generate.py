#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 工具使用场景目录站 —— 自动生成器（零投资版）
抓取新 AI 工具 -> 调用 LLM 生成「定位/使用场景/人群/优缺点/标签」-> 输出静态 HTML
配合 GitHub Actions 每天定时运行，结果提交回仓库，由 Cloudflare Pages 自动发布。

零成本要点：
- 托管：Cloudflare Pages（免费、国内访问最快）
- 调度：GitHub Actions（免费 2000 分钟/月，足够每日跑）
- 抓取：Hacker News Algolia API（无需 key）
- LLM：DeepSeek（约 ¥0.1/百万 token，目录站每月几毛；也可不填 key 先跑通流程）
"""

import json
import os
import re
import html
import datetime
import urllib.request
import urllib.error
import urllib.parse

ROOT = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(ROOT, "public")
DATA = os.path.join(PUBLIC, "data")
SEEN_FILE = os.path.join(DATA, "seen.json")
CONFIG_FILE = os.path.join(ROOT, "config.json")

# ---------- 配置 ----------
DEFAULT_CONFIG = {
    "site_title": "AI 工具使用场景目录",
    "site_tagline": "按使用场景整理值得一试的 AI 工具，每天自动更新",
    "deepseek_api_key": "",                       # 留空也能跑（降级为极简页）
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",
    "queries": ["AI tool", "AI agent", "AI app", "LLM tool"],  # HN 检索词
    "max_new_per_run": 5,                          # 每次最多处理的新工具数
    "days_window": 7,                              # 只看最近 N 天
    "affiliate_note": "部分链接为联盟链接，通过它们注册/购买可支持本站，不影响你的价格。",
    "affiliate_links": {                           # 在工具页底部统一展示的联盟入口（按需替换成你自己的 PID）
        "淘宝联盟": "",
        "京东联盟": "",
        "本站专属福利": ""
    }
}


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg.update(json.load(f))
        except Exception as e:
            print("读取 config.json 失败，使用默认配置：", e)
    # 环境变量优先（用于 GitHub Actions Secret，避免把 key 写进仓库）
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        cfg["deepseek_api_key"] = env_key
    return cfg


# ---------- 抓取 ----------
def fetch_hn_tools(queries, days_window, limit=20):
    """从 Hacker News Algolia 免费 API 抓取近期含 AI 工具的故事。无需 key。"""
    since = int(datetime.datetime.now().timestamp()) - days_window * 86400
    found = []
    for q in queries:
        try:
            url = (
                "https://hn.algolia.com/api/v1/search_by_date"
                f"?query={urllib.parse.quote(q)}&tags=story&numericFilters=created_at_i>{since}&hitsPerPage={limit}"
            )
            with urllib.request.urlopen(url, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8"))
            for hit in data.get("hits", []):
                title = hit.get("title") or ""
                if not title:
                    continue
                found.append({
                    "name": title,
                    "url": hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}",
                    "source": "Hacker News",
                    "points": hit.get("points", 0),
                })
        except Exception as e:
            print("HN 抓取失败（跳过该词）：", q)
    # 去重（按 url）
    seen_urls = set()
    uniq = []
    for t in found:
        if t["url"] in seen_urls:
            continue
        seen_urls.add(t["url"])
        uniq.append(t)
    uniq.sort(key=lambda x: x.get("points", 0), reverse=True)
    return uniq


def load_seed():
    seed_path = os.path.join(ROOT, "seed_tools.json")
    if not os.path.exists(seed_path):
        return []
    try:
        with open(seed_path, "r", encoding="utf-8") as f:
            items = json.load(f)
        for it in items:
            it.setdefault("source", "人工种子")
        return items
    except Exception as e:
        print("读取 seed_tools.json 失败：", e)
        return []


# ---------- LLM ----------
def llm_generate(tool, cfg):
    """调用 DeepSeek 生成结构化介绍。无 key 时返回降级内容。"""
    key = (cfg.get("deepseek_api_key") or "").strip()
    if not key:
        return {
            "tagline": "（未配置 LLM key，待补充介绍）",
            "scenarios": [{"title": "了解更多", "detail": f"访问官网了解详情：{tool['url']}"}],
            "for_whom": "待补充",
            "pros": ["待补充"],
            "cons": ["待补充"],
            "tags": ["AI工具"],
            "category": "其他"
        }
    prompt = (
        "你是一个专业的 AI 工具测评编辑。请用简体中文，针对下面这个 AI 工具，"
        "生成一份「按使用场景」组织的介绍，严格只输出 JSON，不要任何解释。\n"
        "JSON 字段：\n"
        "  name: 工具名\n"
        "  tagline: 一句话定位（不超过 30 字）\n"
        "  category: 分类，从[写作, 编程, 图像, 视频, 音频, 办公, 自动化/Agent, 设计, 研究, 其他]选一个\n"
        "  scenarios: 数组，3-5 个使用场景，每个含 title(场景名) 与 detail(1-2句具体做法)\n"
        "  for_whom: 适合谁用（一句话）\n"
        "  pros: 数组，2-3 个优点\n"
        "  cons: 数组，1-2 个不足\n"
        "  tags: 数组，3-5 个标签(词或短短语)\n\n"
        f"工具名（可能为英文标题，请提取真实工具名）：{tool['name']}\n"
        f"来源链接：{tool['url']}\n"
    )
    try:
        req_body = json.dumps({
            "model": cfg["deepseek_model"],
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.7,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{cfg['deepseek_base_url'].rstrip('/')}/chat/completions",
            data=req_body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=40) as r:
            resp = json.loads(r.read().decode("utf-8"))
        content = resp["choices"][0]["message"]["content"]
        data = json.loads(content)
        data.setdefault("scenarios", [])
        data.setdefault("tags", [])
        data.setdefault("category", "其他")
        return data
    except Exception as e:
        print("LLM 生成失败，降级处理：", tool["name"])
        return {
            "tagline": "（生成失败，待重试）",
            "scenarios": [{"title": "了解更多", "detail": f"访问官网：{tool['url']}"}],
            "for_whom": "待补充", "pros": ["待补充"], "cons": ["待补充"],
            "tags": ["AI工具"], "category": "其他"
        }


# ---------- 渲染 ----------
def slugify(name):
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "-", name.lower()).strip("-")
    return s[:60] or "tool"


CSS = """
:root{--bg:#0f1115;--card:#181b22;--fg:#e8eaed;--muted:#9aa0a6;--accent:#4f8cff;--line:#262b33}
*{box-sizing:border-box}
body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--fg);line-height:1.6}
header{padding:40px 20px 24px;text-align:center;border-bottom:1px solid var(--line)}
header h1{margin:0 0 8px;font-size:28px}
header p{margin:0;color:var(--muted)}
main{max-width:960px;margin:0 auto;padding:24px 16px 60px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 26px}
.chip{background:var(--card);border:1px solid var(--line);color:var(--muted);padding:6px 14px;border-radius:999px;cursor:pointer;font-size:13px}
.chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;display:flex;flex-direction:column;gap:8px;transition:.15s}
.card:hover{border-color:var(--accent);transform:translateY(-2px)}
.card h3{margin:0;font-size:17px}
.card .tagline{color:var(--muted);font-size:13px;min-height:36px}
.card .cat{font-size:12px;color:var(--accent)}
.card a.visit{margin-top:auto;color:var(--accent);text-decoration:none;font-size:14px}
footer{text-align:center;color:var(--muted);font-size:12px;padding:30px 16px;border-top:1px solid var(--line)}
.tool-wrap{max-width:760px;margin:0 auto;padding:24px 16px 60px}
.tool-wrap h1{font-size:26px;margin-bottom:4px}
.tool-wrap .tagline{color:var(--muted);font-size:15px;margin-bottom:20px}
.section{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:16px 0}
.section h2{font-size:16px;margin:0 0 12px;color:var(--accent)}
.scenario{border-left:3px solid var(--accent);padding-left:12px;margin:10px 0}
.scenario b{display:block;margin-bottom:2px}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
.tag{background:#0f1115;border:1px solid var(--line);color:var(--muted);padding:3px 10px;border-radius:999px;font-size:12px}
.back{display:inline-block;margin:18px 0;color:var(--accent);text-decoration:none}
.aff{font-size:12px;color:var(--muted);border-top:1px dashed var(--line);margin-top:18px;padding-top:12px}
"""

TPL_CARD = """
<a class="card" href="tools/{slug}.html" data-cat="{cat}">
  <span class="cat">{cat}</span>
  <h3>{name}</h3>
  <div class="tagline">{tagline}</div>
  <span class="visit">查看使用场景 →</span>
</a>
"""

TPL_TOOL = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} - {site_title}</title>
<style>{css}</style></head>
<body>
<div class="tool-wrap">
<a class="back" href="../index.html">← 返回目录</a>
<h1>{name}</h1>
<div class="tagline">{tagline}</div>
<div class="section"><h2>它是什么</h2><p>分类：<b>{cat}</b> ｜ 来源：{source}</p>
<p><a class="visit" href="{url}" target="_blank" rel="noopener">访问官网 →</a></p></div>
<div class="section"><h2>使用场景</h2>{scenarios}</div>
<div class="section"><h2>适合谁</h2><p>{for_whom}</p></div>
<div class="section"><h2>优点</h2><ul>{pros}</ul></div>
<div class="section"><h2>不足</h2><ul>{cons}</ul></div>
<div class="section"><h2>标签</h2><div class="tags">{tags}</div></div>
<div class="aff">{affiliate_note}<br>{aff_links}</div>
</div>
</body></html>
"""

TPL_INDEX = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__SITE_TITLE__</title>
<style>__CSS__</style></head>
<body>
<header><h1>__SITE_TITLE__</h1><p>__SITE_TAGLINE__</p>
<p style="font-size:12px;color:var(--muted)">最近更新：__UPDATED__</p></header>
<main>
<div class="chips" id="chips"></div>
<div class="grid" id="grid">__CARDS__</div>
</main>
<footer>本目录由 AI 每日自动整理 · 部分链接含联盟佣金</footer>
<script>
const cats=["全部"];document.querySelectorAll('.card').forEach(c=>{const k=c.dataset.cat;if(!cats.includes(k))cats.push(k)});
const chips=document.getElementById('chips');const grid=document.getElementById('grid');
cats.forEach((c,i)=>{const b=document.createElement('span');b.className='chip'+(i===0?' active':'');b.textContent=c;b.onclick=()=>{document.querySelectorAll('.chip').forEach(x=>x.classList.remove('active'));b.classList.add('active');const v=c==='全部'?'*':c;grid.querySelectorAll('.card').forEach(card=>{card.style.display=(v==='*'||card.dataset.cat===v)?'':'none'});};chips.appendChild(b)});
</script>
</body></html>
"""


def esc(s):
    return html.escape(str(s), quote=True)


def render_tool(tool, data, cfg):
    slug = slugify(tool["name"])
    tagline = data.get("tagline", "")
    scenarios = "".join(
        f'<div class="scenario"><b>{esc(s.get("title",""))}</b>{esc(s.get("detail",""))}</div>'
        for s in data.get("scenarios", [])
    )
    pros = "".join(f"<li>{esc(p)}</li>" for p in data.get("pros", []))
    cons = "".join(f"<li>{esc(c)}</li>" for c in data.get("cons", []))
    tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in data.get("tags", []))
    aff = cfg.get("affiliate_note", "")
    aff_links = " ｜ ".join(f'<a href="{esc(v)}" target="_blank" rel="noopener">{esc(k)}</a>'
                           for k, v in (cfg.get("affiliate_links") or {}).items() if v)
    page = TPL_TOOL.format(
        name=esc(tool["name"]), site_title=esc(cfg["site_title"]), css=CSS,
        tagline=esc(tagline), cat=esc(data.get("category", "其他")),
        source=esc(tool.get("source", "")), url=esc(tool["url"]),
        scenarios=scenarios, for_whom=esc(data.get("for_whom", "")),
        pros=pros, cons=cons, tags=tags, affiliate_note=aff, aff_links=aff_links,
    )
    path = os.path.join(PUBLIC, "tools", f"{slug}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    card = TPL_CARD.format(slug=slug, cat=esc(data.get("category", "其他")),
                           name=esc(tool["name"]), tagline=esc(tagline))
    return slug, card, data.get("category", "其他"), tagline


def main():
    cfg = load_config()
    os.makedirs(os.path.join(PUBLIC, "tools"), exist_ok=True)
    os.makedirs(os.path.join(PUBLIC, "css"), exist_ok=True)
    os.makedirs(DATA, exist_ok=True)

    seen = {}
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                seen = json.load(f)
        except Exception:
            seen = {}

    # 合并候选：种子优先（保证首屏有内容），再补 HN 新工具
    candidates = load_seed() + fetch_hn_tools(cfg["queries"], cfg["days_window"])
    new_count = 0
    for tool in candidates:
        uid = tool.get("url") or tool.get("name")
        if uid in seen:
            continue
        if new_count >= cfg["max_new_per_run"]:
            break
        data = llm_generate(tool, cfg)
        slug, card, cat, tagline = render_tool(tool, data, cfg)
        seen[uid] = {"slug": slug, "category": cat, "name": tool["name"], "tagline": tagline}
        new_count += 1
        print(f"已生成：{tool['name']} -> {slug}.html")

    # 重建索引（用 seen 保证完整，且首页卡片带一句话定位）
    cards = []
    for meta in seen.values():
        cards.append(TPL_CARD.format(
            slug=esc(meta.get("slug", "")), cat=esc(meta.get("category", "其他")),
            name=esc(meta.get("name", "")), tagline=esc(meta.get("tagline", "")),
        ))
    index_html = (TPL_INDEX
                  .replace("__SITE_TITLE__", esc(cfg["site_title"]))
                  .replace("__SITE_TAGLINE__", esc(cfg["site_tagline"]))
                  .replace("__CSS__", CSS)
                  .replace("__UPDATED__", datetime.date.today().isoformat())
                  .replace("__CARDS__", "".join(cards)))
    with open(os.path.join(PUBLIC, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

    # 保存 seen + 写入 css
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False, indent=2)
    with open(os.path.join(PUBLIC, "css", "style.css"), "w", encoding="utf-8") as f:
        f.write(CSS)

    print(f"完成：本次新增 {new_count} 条，累计 {len(seen)} 条。")


if __name__ == "__main__":
    main()
