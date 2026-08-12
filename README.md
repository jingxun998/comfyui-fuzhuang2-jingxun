# Fuzhuang2 Jingxun · Gemini 服装工作流

面向 **ComfyUI** 的开源服装图像工作流插件。项目将 Gemini 图像生成/编辑能力封装为 7 个可组合节点，用于模特图生成、虚拟试衣、姿势变化、服装清洗、局部改色与造型设计。

本仓库公开的是实际运行源码，不再把完整代码藏在第二份 ZIP 中。`0.1.0` 在保留原有节点标识和中文字段的基础上，补齐了测试、发布、安全和隐私边界。

## 主要功能

| 节点 | 作用 | 主要输入 | 输出 |
|---|---|---|---|
| Gemini 模特生成器 | 将人物图转为电商棚拍风格模特图 | 输入图片、种子、超时 | 模特图 |
| Gemini 虚拟试衣 | 将服装图穿到指定模特身上 | 模特图、服装图、种子 | 试穿图 |
| Gemini 姿势变换器 | 在尽量保留人物、服装和背景的前提下改变姿势/视角 | 输入图片、姿势预设或自定义姿势 | 变换姿势图 |
| Gemini 服装处理器 | 从复杂图片中提取上装、下装或鞋子，整理为白底平铺商品图 | 输入图片、品类开关 | 清洗后服装图 |
| Gemini 高级调色盘 | 对指定服装部位、配饰或头发进行局部换色 | 图片、颜色描述、目标选择 | 重新着色图 |
| Gemini 造型助手 | 在现有人像上增加服装或配饰，并可由模型智能推荐 | 图片、自定义添加或品类开关 | 造型增强图 |
| Gemini 场合造型师 | 按商务休闲、晚宴、度假等场景重构整体造型 | 模特图、场合选择 | 场合造型图 |

> 生成式图像可能偏离提示词或改变未指定细节。结果应由使用者人工复核，尤其是在商品真实性、人物授权和广告发布场景中。

## 安装

### 方法一：Git 克隆

进入 ComfyUI 的 `custom_nodes` 目录：

```bash
git clone https://github.com/jingxun998/comfyui-fuzhuang2-jingxun.git
cd comfyui-fuzhuang2-jingxun
python -m pip install -r requirements.txt
```

重启 ComfyUI 后，在节点菜单中搜索 `Gemini`。

### 方法二：Release ZIP

下载最新 Release，解压到：

```text
ComfyUI/custom_nodes/comfyui-fuzhuang2-jingxun/
```

然后在 ComfyUI 所使用的 Python 环境中安装 `requirements.txt`，并重启 ComfyUI。

## API 配置

### 推荐：环境变量

在启动 ComfyUI 前设置：

**macOS / Linux**

```bash
export GOOGLE_API_KEY="你的密钥"
```

**Windows PowerShell**

```powershell
$env:GOOGLE_API_KEY="你的密钥"
```

也支持 `GEMINI_API_KEY`。不要把真实密钥写进 GitHub、Issue、截图、工作流 JSON 或公开日志。

### 本地配置文件

复制示例文件：

```bash
cp gemini_config.example.json gemini_config.json
```

然后只在本机填写：

```json
{
  "api_key": "你的密钥",
  "model": "gemini-3.1-flash-image",
  "api_version": "v1",
  "api_mode": "generate_content"
}
```

`gemini_config.json` 与兼容用的 `gemini_api_key.txt` 已被 `.gitignore` 排除。

## 模型与请求方式

默认模型：

```text
gemini-3.1-flash-image
```

覆盖模型：

```bash
export GEMINI_IMAGE_MODEL="其他兼容模型标识"
```

默认使用官方 `generateContent` 请求结构。仅当受信任的兼容服务仍要求旧代理格式时，在本地配置中设置：

```json
{
  "api_mode": "legacy_proxy"
}
```

## 第三方 API 或代理

安全默认值只允许：

```text
https://generativelanguage.googleapis.com
```

如确实需要一个经过你审查的第三方服务，必须同时完成两层授权：

```bash
export GEMINI_ALLOW_CUSTOM_ENDPOINT=1
export GEMINI_ALLOWED_HOSTS="trusted-provider.example.com"
```

再在本地 `gemini_config.json` 中配置该服务，例如：

```json
{
  "api_key": "本地密钥",
  "model": "服务支持的模型标识",
  "base_url": "https://trusted-provider.example.com",
  "api_version": "v1",
  "api_mode": "generate_content",
  "auth_header_name": "Authorization",
  "auth_header_value_template": "Bearer {api_key}"
}
```

也可使用 `query_param_name`，但把密钥放在 URL 查询参数中更容易进入代理日志，应优先使用认证头。

第三方服务会接触节点发送的**提示词、人物/商品图片以及其认证所需的凭证信息**。只有在确认其运营方、隐私政策和数据保留方式后才应启用。

### 远端数据处理

插件自身不保存远端请求日志，但提示词和图片必须发送到所选服务才能生成结果。Google `generateContent` 接口的数据处理、保留和日志规则由 Google 的现行条款与隐私设置决定；本插件不会伪造一个该接口并不支持的请求级关闭字段。处理人物或商业素材前，请先确认你拥有授权并接受所选服务的规则。

### 系统代理

程序默认忽略继承的 `HTTP_PROXY` / `HTTPS_PROXY`，防止 ComfyUI 进程环境中的未知代理静默拦截图片和密钥。明确需要系统代理时：

```bash
export GEMINI_TRUST_ENV_PROXY=1
```

## 可调安全限制

默认限制适合常见商品图。确有需要时，可通过环境变量调整：

| 环境变量 | 默认值 | 作用 |
|---|---:|---|
| `GEMINI_MAX_INPUT_IMAGES` | 3 | 单次输入图片数量 |
| `GEMINI_MAX_INPUT_PIXELS` | 40,000,000 | 每张输入图像素上限 |
| `GEMINI_MAX_INPUT_IMAGE_BYTES` | 24 MiB | 每张编码后输入图上限 |
| `GEMINI_MAX_REQUEST_BYTES` | 96 MiB | 整个 JSON 请求上限 |
| `GEMINI_MAX_RESPONSE_BYTES` | 80 MiB | 整个 HTTP 响应上限 |
| `GEMINI_MAX_OUTPUT_IMAGE_BYTES` | 48 MiB | 解码后输出图字节上限 |
| `GEMINI_MAX_OUTPUT_PIXELS` | 40,000,000 | 输出图像素上限 |
| `GEMINI_MAX_PROMPT_CHARS` | 32,000 | 提示词字符上限 |

限制值设置错误时，节点会停止并给出明确错误，而不是静默降级。

## 工作流示例

### 基础试衣

```text
加载人物图 → Gemini 模特生成器 ┐
                               ├→ Gemini 虚拟试衣 → 预览/保存
加载服装图 → Gemini 服装处理器 ┘
```

### 叠穿

```text
上一张试穿图 + 新服装图 → Gemini 虚拟试衣 → 新试穿图
```

### 造型变化

```text
试穿图 → Gemini 高级调色盘 / Gemini 造型助手 / Gemini 场合造型师
```

## 数据、安全与维护

- 节点只有在执行时才会发起网络请求。
- 代码不调用 Shell，不运行 `eval` / `exec`，不动态安装依赖，也不扫描无关文件。
- HTTP 重定向被禁止；远端错误会做凭证脱敏；响应图会经过格式、大小和解压炸弹检查。
- 固定种子生成结果可进入有总容量限制的内存缓存；进程退出后缓存消失。
- 漏洞请通过 GitHub Security 私下报告，不要在公开 Issue 中粘贴密钥或敏感图片。

详见：

- [`SECURITY.md`](SECURITY.md)
- [`PRIVACY.md`](PRIVACY.md)
- [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md)
- [`docs/MIGRATION_0.1.0.md`](docs/MIGRATION_0.1.0.md)

## 开发与验证

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python scripts/validate_repository.py
python -m pytest -q
```

GitHub Actions 会对提交和 Pull Request 执行仓库校验、Python 测试和 CodeQL 分析；标签发布物由同一提交自动构建，减少源码与 ZIP 漂移。

## 兼容性

`0.1.0` 保留原始版本的：

- 7 个节点 class identifier；
- 节点显示名称；
- 中文输入字段；
- `FUNCTION`、返回类型与返回名称；
- 节点分类和工作流连接关系。

升级细节见迁移文档。

## 许可证

[MIT](LICENSE)
