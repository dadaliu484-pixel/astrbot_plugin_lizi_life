# astrbot_plugin_lizi_life

一个面向 AstrBot 的轻量生活陪伴插件。使用当前会话配置的聊天模型，不单独保存 API Key。

## 功能

- `/状态`：每天稳定生成角色状态
- `/群聊 内容`：模拟多个角色的小群聊
- `/吃什么 [预算]`：按预算给出简单饮食方案
- `/抽任务`、`/完成`、`/成就`：低压力任务与成就
- `/记录 内容`、`/日记`、`/昨日回忆`：只基于主动记录和插件活动生成摘要
- `/今日事件`：每日角色关系网事件
- `/睡觉`、`/起床`：切换普通聊天的晚安短回复模式
- `/今天科研 [主题]`：把科研压力拆成一个小动作
- `/status`：查看云服务器资源及 FRP 后方的健康检查地址

## 安装

在 AstrBot WebUI 中打开“插件管理”，选择从 GitHub 仓库安装，粘贴本仓库 URL。

插件要求 AstrBot `>= 4.9.2`。安装后在插件配置中填写角色、任务、饮食偏好和健康检查地址，然后重载插件。

## FRP 健康检查

`health_endpoints` 每行填写：

```text
本地 Embedding|https://example.com/embedding/health|Bearer令牌内容
LM Studio|https://example.com/lmstudio/v1/models|Bearer令牌内容
```

第三段令牌可省略。插件会使用 `Authorization: Bearer <令牌>` 请求。

不要把 LM Studio 或 embedding 服务无鉴权直接暴露到公网。推荐在本地服务前增加一个只返回健康状态的反向代理接口，并限制 FRP 入口。

## 数据与隐私

状态、任务、成就、主动记录和日记摘要使用 AstrBot 插件 KV 存储。插件不会保存完整聊天记录。动态状态通过临时上下文注入，不写入会话历史。

## 开发检查

```bash
python -m unittest discover -s tests
python -m compileall .
```
