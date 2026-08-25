"""LLM 模型管理与服务配置（DD-20）。

- 模型管理：维护“如何连接一个具备明确能力的模型”（连接信息与凭据）；
- 服务配置：维护“某项业务使用哪个模型配置”（仅保存模型配置 ID）；
- 配置以 schema_version=2 的 revision 存于 platform.config_revisions（namespace=llm），
  密钥独立存于 platform.secret_values（namespace=llm_model）。
"""
