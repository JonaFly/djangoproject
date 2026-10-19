# Crypto 市场「程序化稳定盈利」严格评估（2026-10-19）

> 结论先行：**Binance / Deribit / Polymarket 上确实存在过、也仍然存在可程序化的收益来源，但 2026 年已经没有"很多不成熟市场可以稳定赚高额收益"这件事。**
> 真实可验证的数据指向：规模化、稳定的只有 **资金费率/基差 carry（年化约 10% 毛收益）**；Deribit **波动率溢价当前接近零，不是部署时点**；Polymarket 的 **套利利润被极少数机器人拿走，普通参与者整体亏损**，天气市场等"不成熟"角落容量极小且已被机器人在分钟级抹平。

本目录同时提供一套只依赖标准库的 **真实数据拉取 + 评估工具**（见末尾「如何运行」），用于在你自己的机器上按日复核下面每一个数字。

---

## 1. 数据来源与本次的限制

本次分析在一个出站网络受限的云环境中完成：`www.deribit.com`、`api/fapi/eapi.binance.com`、`gamma-api/clob.polymarket.com`、`api.weather.gov`、`open-meteo.com` 均被策略拒绝（403），因此 **交易所 API 的逐笔/盘口数据没有在本会话里实时拉到**。下文所有数值均来自可公开核验的二手来源（Glassnode、CF Benchmarks、Deribit Insights、学术论文、Bloomberg/Dune 报道等），并逐条标注出处。工具包设计为在放开这些域名或在本地运行后，直接产出同口径的实时快照。

---

## 2. 逐市场核验

### 2.1 Deribit 期权：波动率风险溢价（VRP）

| 指标 | 数值 | 来源 |
|---|---|---|
| BTC DVOL（30 日隐含波动率指数）2026-10-16 收盘 | 37.67（当日区间 36.1–38.8） | [Glassnode DVOL](https://studio.glassnode.com/charts/derivatives.DvolOhlc?a=BTC) |
| DVOL 近一年分位 | 约 5 分位（"便宜"），VRP 读数 ≈ 持平 | [indiciadesk](https://indiciadesk.com/en/vol) |
| 2025 年平均隐含波动率 | 46%；9 月中 DVOL ≈ 40 | [coinperps](https://www.coinperps.com/learn/crypto-options-statistics) |
| 历史上 30 日 IV > 后续 30 日 RV 的比例（2019.4 起） | 接近 70% | [Deribit Insights](https://insights.deribit.com/industry/bitcoin-options-finding-edge-in-four-years-of-volatility-regimes/) |
| 学术证据 | VRP 显著为正、RV 很少超过 IV（Alexander & Imeraj；Almeida/Grith/Miftachov） | [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3383734) / [arXiv 2410.15195](https://arxiv.org/pdf/2410.15195) |
| 尾部事件 | 2025-10-10 单日清算 >$190 亿（有估计 $300–400 亿），顶部盘口深度缩水 >90% | [Reuters via Kitco](https://www.kitco.com/news/off-the-wire/2025-10-14/after-record-crypto-crash-rush-hedge-against-another-freefall) / [FTI](https://www.fticonsulting.com/zh-cn/china/insights/articles/crypto-crash-october-2025-leverage-met-liquidity) |

**判断**：卖波动率在长期样本里有正期望（约 70% 的时间 IV 高于 RV），这是 Deribit 上最"真"的结构性收益。但它不是"稳定"：收益形态是小赚多次、偶尔巨亏，2025-10-10 这类事件对未对冲的空 gamma 头寸是毁灭性的。更关键的是 **当下 DVOL 处在一年最低分位附近、溢价接近持平**，按工具包的 `regime_flag` 口径（IV−RV ≥ 8 vol pts 且 DVOL 分位 ≥ 30%）**现在是 STAND ASIDE**。

### 2.2 Binance / Deribit：资金费率与基差 carry

| 指标 | 数值 | 来源 |
|---|---|---|
| BTC 永续资金费率 2026-10-16/18 | 0.0100% / 8h ≈ 10.9% 年化 | [TokenPost](https://www.tokenpost.com/news/investing/33874) |
| 五所平均 2026-10-16 | ≈ 13.3% 年化 | [DefiRate](https://defirate.com/perp/) |
| CF Kraken 永续资金费率指数 2026-10-17 | 13.48% | [CF Benchmarks](https://www.cfbenchmarks.com/data/indices/KFRI) |
| CME 3 月基差 2026 年中 | ≈ 3% 年化（低于 2 年期美债 3.8%；2024–2025 上半年曾常年 15–20%） | [PrimeXBT](https://primexbt.com/news/binance-overtakes-cme-in-bitcoin-futures-open-interest-as-basis-trade-collapses/) |
| 2026 年费率为负的区间 | "主流币长时间处于负费率" | [Datawallet](https://www.datawallet.com/crypto-funding-rates) |

**判断**：这是唯一 **既可验证、又可放大、又低方差** 的程序化收益。但它本质是"借钱给多头"的利率产品：毛收益约 11–13%，扣掉开平仓四条腿手续费（约 0.3% 往返）和负费率区间，**净年化合理预期 6–10%**，牛市脉冲时可到 20–30%，熊市可归零。风险在交易所信用、ADL（自动减仓）和 2025-10-10 那种基差瞬间错位。

### 2.3 Binance 期权 vs Deribit 跨所

| 指标 | 数值 | 来源 |
|---|---|---|
| Deribit 在加密原生期权中的份额 | 约 85% | [spark.money](https://www.spark.money/tools/bitcoin-options-exchange-comparison) |
| 含 ETF 期权后 Deribit BTC 期权 OI 份额（2026-04） | <39%，IBIT 期权 OI $276 亿一度超过 Deribit $269 亿 | [CoinLaw](https://coinlaw.io/options-market-in-crypto-statistics/) |
| Binance 期权地位 | 边缘，OI 落后 Deribit 与 Bullish | 同上 |

**判断**：Binance 期权流动性薄，与 Deribit 的 IV 差主要是流动性溢价而非错价；两所无法共用保证金，资本效率低；双边手续费（Binance 0.03% 名义/封顶 10% 权利金，Deribit 0.03% 标的/封顶 12.5%）吃掉大部分价差。**没有找到任何公开的、经核验的跨所期权套利收益数据**。工具包里的 `cross_venue_iv.py` 会把两边同到期同行权价的可执行价差扣费后列出，预期绝大多数为负。

### 2.4 Polymarket：谁在赚钱

| 指标 | 数值 | 来源 |
|---|---|---|
| 2024-04 → 2025-04 套利总利润（8,600 万笔下注） | ≈ $4,000 万；前 3 个钱包 10,200 笔赚 $420 万 | [Saguillo et al., AFT 2025, arXiv 2508.03474](https://arxiv.org/pdf/2508.03474) |
| 利润来源 | 政治（2024 美国大选）为主；体育机会多但单笔小 | 同上 |
| Bloomberg/Dune 2026-04 | 亏损 ≥$1,000 的账户 >10 万个（≈ 盈利同额账户的两倍）；除少数机器人外其余合计亏 $1.31 亿 | [Japan Times](https://www.japantimes.co.jp/business/2026/04/28/markets/prediction-market-traders-lose-money/) |
| 链上独立统计 | 9,500 万笔交易中仅 0.51% 钱包盈利 >$1,000 | [Yahoo Finance](https://finance.yahoo.com/news/polymarket-users-lost-millions-dollars-143016473.html) |
| 手续费（V2，2026-03-30 起） | 加密类 taker 7%×p(1−p)，50c 时每 100 股 $1.75；体育 3–5%；maker 0 且返还 taker 费 20–25% | [startpolymarket](https://startpolymarket.com/learn/polymarket-fees/) / [rivermarkets](https://www.rivermarkets.com/insights/polymarket-fees.html) |
| 裁决风险 | 2026 年已 >1,150 个争议市场；Strategy 5 月卖币市场 $8,500 万争议被 98.6% 票维持 "No"；WSJ 称多数争议中 >50% 票来自前 10 钱包 | [The Block](https://theblock.co/post/403600/polymarket-upholds-no-outcome-strategy-bitcoin-sale-market) / [The Defiant](https://thedefiant.io/usd85m-polymarket-dispute-over-strategy-s-may-bitcoin-sale-puts-uma-s-token-voting-oracle-on) |

**判断**："Polymarket 不成熟、程序可以稳赚"这个判断 **在 2024–2025 是对的，2026 已经大幅失效**：$4,000 万的套利利润高度集中在几个机器人；手续费 V2 直接把 15 分钟 BTC 市场和加密类市场的来回成本抬到每股 3–4c；流动性奖励公式已改、几乎拿不到。剩余的真实边际：

- **多结果事件 dutch book**（ΣAsk < 1 或 ΣBid > 1）：仍会出现，但被机器人在秒级吃掉，需要 Polygon 节点 + CLOB 直连；资金锁定到结算，且承担 UMA 裁决风险。
- **天气温度市场**：2026 年公开案例是一个累计约 $8.8 万的钱包（含一笔巴黎 $3 万）和自报 8 天回测 58.7% 胜率 / 15.2% ROI（[GitHub 开源 bot](https://github.com/tobiasbischoff/polymarket-weather-bot)、[Medium 分析](https://medium.com/mountain-movers/inside-the-data-behind-polymarkets-viral-88k-weather-prediction-trading-strategy-and-results-2e65a8389f37)）。边际来源是 GFS/ECMWF 集合预报 vs 人群定价，**真实但容量极小**（单市场流动性几千美元），"机器人在模型更新后数分钟内抹平错价"（[tradetheoutcome](https://www.tradetheoutcome.com/polymarket-weather-strategy/)），且结算源已从 Wunderground 换成 NOAA、巴黎站点因疑似篡改被更换（[nextpredict](https://nextpredict.io/prediction-markets/weather/)）。合理预期：单个成熟 bot 每月 $500–3,000，**无法承载认真资金**。
- **15 分钟 Up/Down 延迟套利**：纯速度游戏（宣称 42–200ms 执行），2026-01 起加 7% taker 费、2026-08-14 起结算改 Chainlink TWAP，新进入者无优势。
- **做市 + 返佣**：唯一公开实盘日志（[Tanuj-07](https://github.com/Tanuj-07/prediction-market-making)，2026-09 起）6 周小资金合计约 +$57，奖励"现在很少"；"每天 $200–800"的说法均为卖 bot 的营销。
- **Kalshi–Polymarket 跨平台**：毛价差 1–5c，扣费、提现延迟（3–30 天）、$25k 持仓上限后净边际≈0。

---

## 3. 策略总评（按可部署性排序）

| # | 策略 | 可核验毛收益 | 合理净年化 | 稳定性 | 容量 | 主要风险 | 当前信号 |
|---|---|---|---|---|---|---|---|
| 1 | 永续资金费率 + 交割基差 carry（Binance/Deribit/OKX 多所轮动） | 10.9–13.5% | 6–10%（牛市 20%+） | 高 | $百万级 | 交易所信用、负费率、ADL | **可部署** |
| 2 | Deribit 卖波动率（delta 对冲 strangle / 卖 DVOL 期货），带波动率分位过滤 | 长期 IV>RV ≈70% 时间 | 10–20% 保证金收益，Sharpe ≈1 | 中低（肥尾） | $十万–百万 | 2025-10-10 型崩盘；回撤 20–40% | **等待**（DVOL 5 分位、VRP≈0） |
| 3 | Polymarket 多结果 dutch book + 做市返佣 | 2024–25 共 $4,000 万，极度集中 | 小资金 10–30%，随规模迅速衰减 | 中 | $1–5 万 | 机器人竞争、UMA 裁决、资金锁定 | 作为研发仓位 |
| 4 | Polymarket 天气（集合预报 vs 市场） | 自报 15% ROI/8 天；$8.8 万钱包 | 月 $500–3k 绝对值 | 低（已被 bot 压缩） | $几千 | 流动性、站点/数据源变更 | 可做学习项目 |
| 5 | Binance ↔ Deribit 期权跨所 | 无公开核验数据 | ≈0 扣费后 | — | — | 资本效率、流动性溢价 | 仅作信号 |
| 6 | 15 分钟 Up/Down 延迟套利 | 仅营销宣称 | 需 <100ms 基础设施 | 低 | — | 7% taker 费、TWAP 结算 | 不建议 |
| 7 | Kalshi–Polymarket 跨平台 | 1–5c 毛价差 | ≈0 | — | — | 提现、限仓、KYC | 不建议 |

**一个"百万美元量化"视角的组合建议**：
- 70% 资金做 **多所 carry**：实时比较 Binance/Deribit/OKX/Bybit 的预测费率与交割基差，只在年化 ≥ 8% 时进场，费率转负超过 3 期即平仓换所。
- 20% 预留给 **Deribit VRP**，只在 `regime_flag == DEPLOY_SHORT_VOL` 时开仓，必须买远 OTM 尾部保护（放弃 2–3 vol pts 换取 2025-10-10 幸存）。
- 10% 作为 **Polymarket 研发仓**：跑 `polymarket_scan.py` 的 dutch book 与天气模块，验证自己能否在费后、滑点后拿到正边际；拿不到就停。
- 组合目标：**净年化 10–15%，Sharpe ≈ 2，最大回撤 <10%**。任何宣称"稳定年化 50%+"的程序，在上述公开数据里找不到任何一例经独立核验的支持。

---

## 4. 如何运行（真实数据）

```bash
cd crypto_edge_research
python3 -m unittest discover -s tests      # 16 个纯数学/解析用例，离线可跑
python3 run_all.py                          # 拉实时数据，生成 reports/snapshot_<UTC>.md 与 .json
python3 deribit_vrp.py BTC                  # 单独跑：DVOL vs 后 30 日 RV、期限结构、25d skew、部署信号
python3 binance_carry.py BTCUSDT            # 单独跑：8h 费率 7/30/90 日年化、交割基差、扣费 carry
python3 cross_venue_iv.py                   # 单独跑：Binance eapi vs Deribit 同到期同行权价扣费价差
python3 polymarket_scan.py --json           # 单独跑：dutch book、天气 vs GFS 31 成员、长尾 NO 年化、Up/Down 成本
```

需要放行的域名：`www.deribit.com`、`fapi.binance.com`、`eapi.binance.com`、`gamma-api.polymarket.com`、`clob.polymarket.com`、`ensemble-api.open-meteo.com`、`geocoding-api.open-meteo.com`。全部为公开端点，无需 API key。所有模块只依赖 Python 3.10+ 标准库。

每个模块的费率常量（`FEE_RATES`、`DEFAULT_FEES`、`BINANCE_FEE_*`、`DERIBIT_FEE_*`）都写在文件顶部，交易前请按各所当前费率表核对。
