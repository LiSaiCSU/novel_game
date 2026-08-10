---
role: structured_repair
version: v1
output_schema: null
temperature: 0.0
max_output_tokens: 700
---
你上一次的输出未通过校验。

校验错误：{{error}}

上一次输出：
{{previous}}

请只返回一个符合以下结构的 JSON 对象，不要附加解释、散文或 Markdown 代码围栏：
{{schema}}
