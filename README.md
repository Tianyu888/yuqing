# 苏移舆情预充值卡商户跑路风险预警

用于拉取苏移舆情专题数据，筛选江苏省无锡市范围内的预充值卡商户跑路、闭店、失联、拒不退款等风险舆情，并输出 Excel 预警清单。

## 功能

- 支持调用苏移舆情 API，或读取本地 `xlsx/json/csv` 文件离线处理。
- 支持 `cpu/gpu` 两种模式：
  - `cpu`：只使用本地规则。
  - `gpu`：CPU 规则优先，只把必要记录交给大模型复核，并使用大模型辅助去重。
- 地域过滤覆盖全国地级市和直辖市，目标城市默认 `无锡市`。
- 去重包括 URL、全文、同门店/公司同事件、相似文案、最终复核后去重和大模型同事件归并。
- 配置从 `.env` 读取；如果 `.env` 不存在，脚本会自动创建模板。

## 安装

```bat
cd /d D:\yuqing
D:\Anaconda\python.exe -m pip install -r requirement.txt
```

## 配置

复制 `.env.example` 为 `.env`，或直接运行脚本自动创建 `.env`，然后填写：

```text
SUYIYU_APP_KEY=
SUYIYU_SECURE_KEY=
LLM_API_URL=
LLM_API_KEY=
LLM_MODEL=
```

`.env` 已加入 `.gitignore`，不要提交真实密钥。

## 测试 API 连通性

测试舆情 API：

```bat
D:\Anaconda\python.exe D:\yuqing\scripts\test_yuqing_api.py
```

测试大模型 API：

```bat
D:\Anaconda\python.exe D:\yuqing\scripts\test_llm_api.py
```

测试通过后，脚本会询问是否把本次参数写入 `.env`。

## 运行

只使用本地规则：

```bat
D:\Anaconda\python.exe D:\yuqing\suyiyu_prepaid_risk.py ^
  --analysis-mode cpu ^
  --output D:\yuqing\outputs\预充值卡商户跑路风险预警输出.xlsx
```

使用大模型辅助复核和智能去重：

```bat
D:\Anaconda\python.exe D:\yuqing\suyiyu_prepaid_risk.py ^
  --analysis-mode gpu ^
  --date-type 30 ^
  --output D:\yuqing\outputs\预充值卡商户跑路风险预警输出.xlsx
```

读取本地文件离线处理：

```bat
D:\Anaconda\python.exe D:\yuqing\suyiyu_prepaid_risk.py ^
  --input D:\yuqing\input.xlsx ^
  --analysis-mode cpu ^
  --output D:\yuqing\outputs\offline_output.xlsx
```

## 项目结构

```text
yuqing_prepaid_risk/
  api.py          # 舆情 API 请求
  cli.py          # 命令行入口
  config.py       # 默认配置和关键词
  dedup.py        # 规则去重和大模型辅助去重
  env.py          # .env 创建、读取、更新
  io_utils.py     # 文件读写和 Excel 输出
  llm.py          # 大模型风险复核和去重判断
  models.py       # 数据结构
  pipeline.py     # 主处理流程
  rules.py        # 地域过滤、风险分类、摘要提取
  utils.py        # 通用文本工具
scripts/
  test_yuqing_api.py
  test_llm_api.py
suyiyu_prepaid_risk.py # 兼容入口
```

更详细的参数和规则说明见 `苏移舆情预充值风险脚本使用方式.md`。
