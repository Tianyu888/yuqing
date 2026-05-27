"""苏移舆情预充值卡商户跑路风险预警处理包。"""

__version__ = "1.0.0"

__all__ = [
    "LlmApiTestOptions",
    "RawExportOptions",
    "RiskAnalysisOptions",
    "YuqingApiTestOptions",
    "export_raw_yuqing",
    "fetch_raw_yuqing_rows",
    "run_risk_analysis",
    "test_llm_api",
    "test_yuqing_api",
]


def __getattr__(name: str):
    if name in __all__:
        from . import service

        return getattr(service, name)
    raise AttributeError(name)
