# 资料与引用约定

仅导入具有明确公版或授权依据的文本。每个来源必须在 `data/sources` 的清单中记录书名、版本、来源链接、文件路径、主题标签以及 `license_basis`。导入程序会拒绝缺少这些字段的资料。

开发用 `data/sources/manifest.example.json` 和 `sample/zhouyi.md` 只用于验证引用链路。正式典籍文本应保存在本地受控目录或私有存储中，不能在未确认许可时提交至仓库。

每个入库片段均携带 `source_id`、书名、章节定位、标签和内容哈希。接口展示的引用必须来自检索结果；模型未看到的资料不得被写为依据。

## 已审核的六十四卦原文包

`manifest.freizl-yijing.json` 记录了 `freizl/yijing` 的简体中文 `64gua.json`。该仓库声明 MIT License，导入器固定 Git revision，保留来源文件、SHA-256、卦的二进制键和每条文本定位。

安装 API 包后，执行以下命令可下载归档并导入 64 条卦辞、384 条按爻位检索的爻辞：

`yijing-import-freizl-yijing`