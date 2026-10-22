# 中文水产标准来源实测（2026-10-21）

> 范围：现行有效的国家标准（GB/GB/T）、行业标准（SC/T、NY/T 等）、地方标准（DB）。
> 方法：`curl` 实测（浏览器 UA、请求间隔 ≥2s），只记录**真实响应**；未登录、未破验证码、未抓取 `robots.txt` 禁止的站点。
> 结论先行：**地方标准（dbba）是唯一可合法批量拿到 PDF 全文的渠道**；行业标准（hbba）大部分可下载 PDF 但多为扫描件；
> 国家标准（openstd）**只有图片式在线预览，无文字层，下载需验证码**，只能记元数据。

## 一、来源逐项实测

| # | 来源 | URL | HTTP 实测 | robots.txt | 可抓取 | 全文可得性 |
|---|---|---|---|---|---|---|
| 1 | 国家标准全文公开系统 | <https://openstd.samr.gov.cn/bzgk/gb/> | 首页/检索/详情 200；`showGb?type=online` 200（图片阅读器）；`type=download` 200（**验证码页**） | 404（无文件） | 是 | **仅在线预览**：逐页背景图（`bg=` token），无文字层；下载走 CAPTCHA，不可自动化 |
| 2 | 全国标准信息公共服务平台 | <https://std.samr.gov.cn/> | 首页 200；`/gb/search/gbQueryPage` 200 JSON；`gbDetailed` 200；`/org/search/stdByTCStdPage` 200 JSON | 404（无文件） | 是 | **仅元数据**（标准号/名称/状态/发布/实施/代替关系），无全文 |
| 3 | 行业标准信息服务平台（SC/T、NY/T…） | <https://hbba.sacinfo.org.cn/> | `stdQueryList` 200 JSON；`stdDetail/<pk>` 200；`portal/online/<pk>` 200；`portal/download/<pk>` 200 `application/pdf` | 302 → SSO 登录页（未提供 robots 策略） | 是（公开页） | **PDF 可下载**（无需登录），但多为扫描件；`attachment/downloadStdFile` 会跳登录，勿用 |
| 4 | 地方标准信息服务平台（DB） | <https://dbba.sacinfo.org.cn/> | 同上，`stdQueryList` 200 JSON；`portal/download/<pk>` 200 `application/pdf` | 302 → SSO 登录页 | 是（公开页） | **PDF 可下载**，多数为文字版 PDF |
| 5 | 农业农村部（含渔业局、质量安全标准栏） | <https://www.moa.gov.cn/> | `robots.txt` 200：`User-agent:* / Disallow:/` | **Disallow: /** | **否** | 按约束**未抓取**；需人工下载 |
| 6 | 渔业渔政管理局 | <https://yyj.moa.gov.cn/> | `robots.txt` 404（nginx） | 无文件 | 政策上按 moa 处理，**未抓取** | 未评估 |
| 7 | 全国水产标准化技术委员会（TC156） | <https://std.samr.gov.cn/search/orgDetailView?tcCode=TC156> | 200 | 404 | 是 | 仅委员会与标准清单元数据，无全文 |
| 8 | 中国水产科学研究院 | <https://www.cafs.ac.cn/> | 200 | 404 | 是 | 只有标准相关新闻，**无标准全文库** |
| 9 | 全国水产技术推广总站 | <http://www.nftec.agri.cn/> | 200（HTTPS 证书主机名不匹配，用 http） | 未取到 | 是 | 标准发布/计划类**通知**，无全文 |
| 10 | 食品安全国家标准检索平台（GB 31650 等） | <https://sppt.cfsa.net.cn/> | 302 → `/goto/blogin` | — | 否（登录墙） | **不可得**；GB 31650 系列在 std.samr/openstd 中查不到 |

要点：

- openstd 与 std.samr 的 `robots.txt` 均 404，即无禁止规则；实测未触发限流。
- `openstd` 的“下载标准”按钮统一进入验证码页（`checkCode`/`验证码`），属于访问控制，**不绕过**。
- `hbba`/`dbba` 的 `robots.txt` 被 302 到统一身份登录页，未返回任何 `Disallow` 规则；实际公开检索/详情/PDF 均无需登录。
- `www.moa.gov.cn` 明确 `Disallow: /`，本次**零请求正文**，仅读取 robots。

## 二、可枚举的“现行”水产标准

判定口径：平台 `status=现行` **且** 实施日期 ≤ 2026-10-21；`废止`、`有更新版`、`即将实施` 一律不计。

| 层级 | 枚举口径 | 现行数量 | 说明 |
|---|---|---|---|
| 国家标准 GB/GB/T | TC156（全国水产标准化技术委员会）全部标准 | **212**（总 341，废止 129） | 权威口径；每条有 `std.samr` 详情 URL 与 openstd `hcno` |
| 国家标准（关键词补充） | 水产/养殖/渔/虾/鱼/饲料/水质 检索去重 | 208 | 与 TC156 高度重叠；额外含 GB 11607-1989 等非 TC156 标准 |
| 行业标准（宽口径） | 水产/养殖/渔/虾/蟹/鱼/贝/藻/苗种 检索去重 | **631**（已实施 626） | 含渔船、渔具、水产加工 |
| 行业标准（严格水产养殖） | 养殖/苗种/亲虾/饲料/病害/水质/尾水/稻渔… | **297** | 其中 SC/T **199**、NY/T 23、SN/T 47 |
| 行业标准 SC/T（全部渔业） | 上述宽口径中 SC/T | 360 | 含渔船/渔具/加工 |
| 地方标准 DB | 水产/养殖/渔/虾/蟹/鱼/贝/藻 检索去重 | **1157** | 覆盖 105 个省市；含“有更新版”76 条已剔除 |

> 计数是**可枚举下界**：关键词检索 + TC156 清单，未穷举所有可能标题（如“海带”“鲍”“珍珠”只部分覆盖）。

## 三、全文可得性（关键结论）

| 层级 | 元数据 | 全文 PDF | 文字层（可直接解析） | 结论 |
|---|---|---|---|---|
| GB | 212 条 | **0**（下载需验证码） | 0 | 201/212 有 openstd 图片预览（如 GB/T 22213-2026 共 31 页），仅能人工阅读，**不可入库** |
| 行业 SC/T | 199 条 | **191**（96%） | 抽样约 20–25% | 8 条 1999–2001 年老标准无公开文本；2019 年及以前基本是扫描件，2022 年后多为文字版 |
| 地方 DB | 1157 条 | 抽样 28/30（93%） | 抽样 12/15（80%） | 新版（2021+）基本为文字版 PDF；2009–2010 老标准有扫描件 |

抽样明细：

- SC/T 12 份随机样本：3 份有文字层（SC/T 3067-2025、2129-2025、5110-2025），9 份 0 字符（2014–2020 扫描件）。
- SC/T 2022 年批次 4/4 有文字层；2020 年及以前 8/8 为扫描件。
- DB 10 份样本：9 份文字版（1 份空文件），另 5 份早样本中 3 份文字版、2 份扫描件。

## 四、证据（标准号 + 标题 + 状态 + 实施日期 + 链接）

1. **GB/T 22213-2026 水产养殖术语** — 现行；发布 2026-02-27；实施 2026-09-01；全部代替 GB/T 22213-2008（已废止）。
   - 元数据：<https://std.samr.gov.cn/gb/search/gbDetailed?id=4C1BF798CB3A83B0E06397BE0A0A640A>
   - 预览：<https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=A4BED9182CF9610E2970DEC2C3A97150>（31 页图片，无文字层）
2. **SC/T 3505-2025 水产粉末油脂** — 现行；发布 2025-12-09；实施 2026-05-01；代替 SC/T 3505-2006。
   - 详情：<https://hbba.sacinfo.org.cn/stdDetail/7dfed4556657829a285af4e59f6d7e7fc9591e59ba6088cbbef612bcba1d2206>
   - PDF：<https://hbba.sacinfo.org.cn/portal/download/7dfed4556657829a285af4e59f6d7e7fc9591e59ba6088cbbef612bcba1d2206>（8 页 / 1.0 MB，含文字层 4,663 字）
3. **DB21/T 4311—2025 饵料用活河蟹出口质量控制技术规范** — 现行；发布 2025-11-27；实施 2025-12-27（辽宁省）。
   - 详情：<https://dbba.sacinfo.org.cn/stdDetail/8548ecb86260c41e71d81c3a00484dd7127244855768ae170ae42f174fb1fcfd>
   - PDF：<https://dbba.sacinfo.org.cn/portal/download/8548ecb86260c41e71d81c3a00484dd7127244855768ae170ae42f174fb1fcfd>（7 页 / 182 KB，含文字层）

## 五、可复现的枚举端点

```text
# 国标检索（JSON，含 STATE / ISSUE_DATE / ACT_DATE）
GET https://std.samr.gov.cn/gb/search/gbQueryPage?searchText=水产&pageSize=100&pageNumber=1
# TC156 委员会标准清单（tid=3 国标，tid=4 行业标准）
GET https://std.samr.gov.cn/org/search/stdByTCStdPage?tid=3&tcCode=TC156&pageNumber=1&pageSize=500
# 行业标准检索（POST 表单；返回 status/actDate/pk/code/chName）
POST https://hbba.sacinfo.org.cn/stdQueryList   current=1&size=200&key=水产
# 地方标准检索
POST https://dbba.sacinfo.org.cn/stdQueryList   current=1&size=200&key=水产
# 详情 / 阅读器 / PDF
https://{hbba,dbba}.sacinfo.org.cn/stdDetail/<pk>
https://{hbba,dbba}.sacinfo.org.cn/portal/online/<pk>
https://{hbba,dbba}.sacinfo.org.cn/portal/download/<pk>   # 无需登录，200 application/pdf
# 国标详情 / 预览 / 下载
https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=<hcno>
https://openstd.samr.gov.cn/bzgk/std/showGb?type=online&hcno=<hcno>
https://openstd.samr.gov.cn/bzgk/std/showGb?type=download&hcno=<hcno>   # 验证码页
```

## 六、与本仓库工具的适配问题

- `scripts/discover.py` 只解析 `<a href>`：openstd 用 `onclick="showInfo(...)"`，hbba/dbba 是 POST JSON，**三个平台都无法用现有 discover 枚举**。
- `scripts/download_html.py` 只保存 HTML 到 `data/inbox/`；标准全文是 PDF，走 `portal/download/<pk>`，现有下载器不适用（本次未改代码）。
- 元数据落点：`download_html.py` 的 `meta.json` 无标准号/状态/实施日期字段。不改 schema 的做法是把状态写进 title（如 `SC/T 3505-2025 水产粉末油脂（现行，实施2026-05-01）`），并在 `data/meta/` 旁挂 sidecar JSON。

## 七、合规记录

- 未抓取 `www.moa.gov.cn`（`Disallow: /`），未尝试任何登录/验证码/付费墙绕过。
- openstd 只验证“预览可达”，未批量抓取预览图片，未 OCR 预览页（图片阅读器的“仅供参考、不得复制”约束）。
- hbba/dbba 只访问公开检索与公开 PDF 端点；`attachment/downloadStdFile?pk=` 会跳登录，已弃用。
- 请求间隔 ≥2s，UA 为普通浏览器。