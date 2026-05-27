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
python -m pip install -r requirement.txt
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

大模型接口需要使用 OpenAI-compatible 的 Chat Completions 协议。`LLM_API_URL` 请填写完整接口地址，不是只填网关域名；常见格式是：

```text
https://你的模型网关/v1/chat/completions
```

如果你的网关把版本号放在其他路径里，也可以是 `https://你的模型网关/chat/completions`。关键是该地址必须能接收 `model`、`messages`，并返回 `choices[0].message.content`。

注意：`analysisMode=gpu` / `--analysis-mode gpu` 会强制要求大模型配置完整。如果请求参数和 `.env` 都没有配置 `LLM_API_URL`、`LLM_API_KEY`、`LLM_MODEL`，接口会返回：`analysisMode=gpu 模式下需要配置大模型，请查阅文档进行大模型API的相关配置`。如果只想使用本地规则，请使用 `cpu` 模式，或显式设置 `disableLlm=true` / `--disable-llm`。

`.env` 已加入 `.gitignore`，不要提交真实密钥。

## 测试 API 连通性

测试舆情 API：

```bat
python scripts\test_yuqing_api.py
```

测试大模型 API：

```bat
python scripts\test_llm_api.py
```

测试通过后，脚本会询问是否把本次参数写入 `.env`。

## 导出原始舆情

如需直接获取舆情 API 返回的完整原始结果，不做地域过滤、风险过滤、去重和大模型复核，可以运行：

```bat
python scripts\export_yuqing_api.py ^
  --date-type 30 ^
  --output outputs\舆情API原始结果.xlsx
```

该脚本会按页拉取 API 数据，并把返回记录中的所有字段写入 Excel。

注意：舆情 API 当前限制单页数量，默认 `--page-count 20`。脚本会自动翻页直到拉完全部数据，不需要手动逐页运行。

## Web 控制台

也可以启动浏览器页面配置参数、运行任务并查看实时日志：

```bat
python scripts\web_ui.py
```

启动后打开：

```text
http://127.0.0.1:8765
```

页面支持两类任务：

- 风险筛选输出：等价于运行 `suyiyu_prepaid_risk.py`，支持 `cpu/gpu`、时间范围、输出路径、模型参数、去重参数等配置。
- 原始舆情导出：等价于运行 `scripts\export_yuqing_api.py`，只拉取 API 原始结果并写入 Excel。

页面会动态显示每个参数的含义，并实时展示脚本输出日志。

## HTTP API 服务

如果要让其他系统通过 `http://ip:port/route` 调用，可以启动 FastAPI HTTP API 服务：

```bat
python scripts\http_api.py --host 0.0.0.0 --port 8770
```

本机测试可以打开：

```text
http://127.0.0.1:8770/api/routes
```

Swagger 文档地址：

```text
http://127.0.0.1:8770/docs
```

主要路由：

```text
GET  /health
GET  /api/routes
POST /api/risk-analysis
POST /api/raw-export
POST /api/test-yuqing
POST /api/test-llm
POST /api/jobs/risk-analysis
POST /api/jobs/raw-export
GET  /api/jobs/{job_id}
```

风险筛选同步调用：

```bat
curl -X POST http://127.0.0.1:8770/api/risk-analysis ^
  -H "Content-Type: application/json" ^
  -d "{\"options\":{\"analysisMode\":\"gpu\",\"dateType\":30,\"output\":\"outputs\\预充值卡商户跑路风险预警输出.xlsx\"},\"write_output\":true,\"include_items\":false}"
```

完整 30 天任务可能耗时较长，更推荐异步调用：

```bat
curl -X POST http://127.0.0.1:8770/api/jobs/risk-analysis ^
  -H "Content-Type: application/json" ^
  -d "{\"options\":{\"analysisMode\":\"gpu\",\"dateType\":30,\"output\":\"outputs\\预充值卡商户跑路风险预警输出.xlsx\"},\"write_output\":true,\"include_items\":false}"
```

返回 `job_id` 后查询状态：

```bat
curl http://127.0.0.1:8770/api/jobs/你的job_id
```

导出原始舆情：

```bat
curl -X POST http://127.0.0.1:8770/api/raw-export ^
  -H "Content-Type: application/json" ^
  -d "{\"options\":{\"dateType\":30,\"output\":\"outputs\\舆情API原始结果.xlsx\"},\"write_output\":true,\"include_rows\":false}"
```

测试连通性：

```bat
curl -X POST http://127.0.0.1:8770/api/test-yuqing -H "Content-Type: application/json" -d "{}"
curl -X POST http://127.0.0.1:8770/api/test-llm -H "Content-Type: application/json" -d "{}"
```

请求参数放在 `options` 里，支持脚本参数的 snake_case 写法，也支持常见 camelCase 写法，例如 `date_type`/`dateType`、`analysis_mode`/`analysisMode`。服务默认读取 `.env`。如果要简单保护接口，可以启动时加 `--token`，请求时带 `Authorization: Bearer <token>`。

## 外部服务调用 API

命令行脚本现在都复用 `yuqing_prepaid_risk.service` 服务层，外部 Python 服务可以直接 import 调用，不需要再用 subprocess 拼命令。

风险筛选，等价于 `suyiyu_prepaid_risk.py`：

```python
from yuqing_prepaid_risk.service import RiskAnalysisOptions, run_risk_analysis

result = run_risk_analysis(
    RiskAnalysisOptions(
        analysis_mode="gpu",
        date_type=30,
        output="outputs/预充值卡商户跑路风险预警输出.xlsx",
    ),
    write_output=True,
    include_items=False,
)
print(result["stats"])
```

导出原始舆情，等价于 `scripts\export_yuqing_api.py`：

```python
from yuqing_prepaid_risk.service import RawExportOptions, export_raw_yuqing

result = export_raw_yuqing(
    RawExportOptions(
        date_type=30,
        output="outputs/舆情API原始结果.xlsx",
    )
)
print(result["row_count"])
```

连通性测试，等价于 `scripts\test_yuqing_api.py` 和 `scripts\test_llm_api.py`：

```python
from yuqing_prepaid_risk.service import test_llm_api, test_yuqing_api

yuqing_result = test_yuqing_api()
llm_result = test_llm_api()
```

这些 API 默认读取 `.env`；也可以在 `RiskAnalysisOptions`、`RawExportOptions`、`YuqingApiTestOptions`、`LlmApiTestOptions` 里显式传入 key、模型地址、分页参数等。`run_risk_analysis(..., include_items=True)` 会返回处理后的明细列表；只想让服务后台生成 Excel 时建议设为 `False`，减少内存占用。

## 运行

只使用本地规则：

```bat
python suyiyu_prepaid_risk.py ^
  --analysis-mode cpu ^
  --output outputs\预充值卡商户跑路风险预警输出.xlsx
```

使用大模型辅助复核和智能去重：

```bat
python suyiyu_prepaid_risk.py ^
  --analysis-mode gpu ^
  --date-type 30 ^
  --output outputs\预充值卡商户跑路风险预警输出.xlsx
```

读取本地文件离线处理：

```bat
python suyiyu_prepaid_risk.py ^
  --input input.xlsx ^
  --analysis-mode cpu ^
  --output outputs\offline_output.xlsx
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
  service.py      # 外部服务调用 API
  utils.py        # 通用文本工具
scripts/
  test_yuqing_api.py
  test_llm_api.py
  export_yuqing_api.py
  http_api.py
  web_ui.py
suyiyu_prepaid_risk.py # 兼容入口
```

更详细的参数和规则说明见 `苏移舆情预充值风险脚本使用方式.md`。
