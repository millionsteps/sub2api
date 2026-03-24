# Sub2API 凭证管理接口

本文档说明 `sub2api` 管理员侧与凭证同步相关的核心接口：

- 导出远程账号导入包：`POST /api/v1/admin/accounts/export-data`
- 按文件名查询远程账号：`POST /api/v1/admin/accounts/get-by-file-names`
- 按文件名覆盖上传：`POST /api/v1/admin/accounts/replace-by-file-names`

兼容保留接口：

- 普通导入：`POST /api/v1/admin/accounts/data`
- 按文件名删除：`POST /api/v1/admin/accounts/delete-by-file-names`

适用场景：

- 已经有 `sub2api-data` 导入包，直接导入到远程 `sub2api`
- 手里只有 `CLIProxyAPIPlus` 的原始凭证文件，需要先本地转换再上传
- 需要根据原始凭证文件名，删除远程 `sub2api` 中对应的账号

## 1. 认证方式

两个接口都需要管理员 Token：

```http
Authorization: Bearer <管理员Token>
Content-Type: application/json
Accept: application/json
```

### 1.1 如何获取管理员 Token

仓库内已提供获取 Token 的辅助脚本：

```bash
python tools/get_sub2api_token.py \
  --mode login \
  --base-url "http://127.0.0.1:8080" \
  --email "admin@example.com" \
  --password "你的密码" \
  --raw-only
```

如果你想直接读取当前浏览器已登录会话导出的 localStorage：

```bash
python tools/get_sub2api_token.py \
  --mode localstorage \
  --localstorage-json "D:\path\to\localstorage.json" \
  --raw-only
```

当前前端本地使用的键为：

- `auth_token`
- `refresh_token`
- `token_expires_at`

## 2. 导出接口

### 2.1 路径

```http
POST /api/v1/admin/accounts/export-data
```

### 2.2 请求参数

```json
{
  "platforms": ["openai", "antigravity"],
  "types": ["oauth"],
  "include_proxies": true
}
```

可选字段：

- `ids`
  按账号 ID 精确导出
- `platforms`
  过滤平台，如 `openai`、`antigravity`
- `types`
  过滤账号类型，如 `oauth`
- `statuses`
  过滤状态，如 `active`
- `search`
  按账号名模糊过滤
- `include_proxies`
  是否带上代理配置，默认 `true`

### 2.3 返回示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "type": "sub2api-data",
    "version": 1,
    "exported_at": "2026-03-25T00:00:00Z",
    "proxies": [],
    "accounts": [
      {
        "name": "codex-demo@example.com",
        "platform": "openai",
        "type": "oauth",
        "credentials": {
          "access_token": "...",
          "refresh_token": "...",
          "email": "demo@example.com"
        },
        "concurrency": 3,
        "priority": 50
      }
    ]
  }
}
```

## 3. 按文件名查询接口

### 3.1 路径

```http
POST /api/v1/admin/accounts/get-by-file-names
```

### 3.2 请求参数

```json
{
  "file_names": [
    "demo@example.com.json",
    "antigravity-demo@example.com.json"
  ]
}
```

### 3.3 返回示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "requested_files": 2,
    "matched_files": 1,
    "not_found_files": 1,
    "results": [
      {
        "file_name": "demo@example.com.json",
        "platform": "openai",
        "type": "oauth",
        "candidate_names": ["codex-demo@example.com"],
        "matched_account_ids": [101],
        "matched_accounts": [
          {
            "id": 101,
            "name": "codex-demo@example.com",
            "platform": "openai",
            "type": "oauth"
          }
        ]
      }
    ]
  }
}
```

## 4. 覆盖上传接口

### 4.1 路径

```http
POST /api/v1/admin/accounts/replace-by-file-names
```

### 4.2 请求参数

```json
{
  "file_names": [
    "alice427dcd@pnj.sixthirtydance.org.json",
    "antigravity-artemisultra662155@bngg.dsckck.com.json"
  ],
  "data": {
    "type": "sub2api-data",
    "version": 1,
    "exported_at": "2026-03-24T13:30:56Z",
    "proxies": [],
    "accounts": [
      {
        "name": "codex-alice427dcd@pnj.sixthirtydance.org",
        "platform": "openai",
        "type": "oauth",
        "credentials": {
          "access_token": "xxx",
          "refresh_token": "xxx",
          "id_token": "xxx",
          "email": "alice427dcd@pnj.sixthirtydance.org",
          "chatgpt_account_id": "xxx",
          "expires_at": "2026-04-03T21:12:14+08:00"
        },
        "extra": {
          "openai_oauth_responses_websockets_v2_enabled": true
        },
        "concurrency": 3,
        "priority": 50
      }
    ]
  },
  "skip_default_group_bind": true
}
```

### 4.3 关键字段说明

- `file_names`
  必传，用于定位需要被替换的远程账号
- `data.type`
  必传，固定为 `sub2api-data`
- `data.version`
  必传，当前固定为 `1`
- `data.proxies`
  必传，可为空数组
- `data.accounts`
  必传，账号列表
- `accounts[].name`
  必传，账号名称
- `accounts[].platform`
  必传，常见值：`openai`、`antigravity`
- `accounts[].type`
  必传，当前凭证导入一般使用 `oauth`
- `accounts[].credentials`
  必传，账号凭证内容
- `accounts[].extra`
  可选，账号附加配置
- `accounts[].concurrency`
  必传，账号并发数，`>= 0`
- `accounts[].priority`
  必传，账号优先级，`>= 0`
- `skip_default_group_bind`
  可选，建议传 `true`，避免导入时自动绑定默认分组

### 4.4 curl 调用示例

```bash
curl -X POST "http://127.0.0.1:8080/api/v1/admin/accounts/replace-by-file-names" \
  -H "Authorization: Bearer <管理员Token>" \
  -H "Content-Type: application/json" \
  --data-binary @sub2api-import-alice-artemis.json
```

### 4.5 返回示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "requested_files": 2,
    "matched_files": 2,
    "deleted_accounts": 2,
    "not_found_files": 0,
    "proxy_created": 0,
    "proxy_reused": 0,
    "proxy_failed": 0,
    "account_created": 2,
    "account_failed": 0
  }
}
```

## 5. 普通导入接口

### 5.1 路径

```http
POST /api/v1/admin/accounts/data
```

### 5.2 说明

该接口直接导入 `sub2api-data` 包，不做覆盖删除。
如果你要做“远程已有账号先删再传”，优先使用：

- `POST /api/v1/admin/accounts/get-by-file-names`
- `POST /api/v1/admin/accounts/replace-by-file-names`

## 6. 按文件名删除接口

### 6.1 路径

```http
POST /api/v1/admin/accounts/delete-by-file-names
```

### 6.2 请求参数

```json
{
  "file_names": [
    "alice427dcd@pnj.sixthirtydance.org.json",
    "antigravity-artemisultra662155@bngg.dsckck.com.json"
  ],
  "dry_run": false
}
```

### 6.3 字段说明

- `file_names`
  必传，凭证文件名数组
- `dry_run`
  可选，传 `true` 时只匹配，不实际删除

### 6.4 文件名匹配规则

当前接口内置以下映射规则：

- `antigravity-<email>.json`
  删除远程账号名 `antigravity-<email>`，平台 `antigravity`，类型 `oauth`
- `<email>.json`
  删除远程账号名 `codex-<email>`，平台 `openai`，类型 `oauth`
- `codex-<email>.json`
  删除远程账号名 `codex-<email>`，平台 `openai`，类型 `oauth`
- `codex-<email>-plus.json`
  尝试映射到远程账号名 `codex-<email>`
- `codex-<hash>-<email>-team.json`
  尝试映射到远程账号名 `codex-<email>`

说明：

- 删除时按“账号名 + 平台 + 类型”做精确匹配
- 若同名账号存在多条，接口会删除所有精确匹配的账号
- 若文件名无法识别，会在结果里返回错误，但接口整体仍返回 `code=0`

### 6.5 curl 调用示例

先预览匹配结果：

```bash
curl -X POST "http://127.0.0.1:8080/api/v1/admin/accounts/delete-by-file-names" \
  -H "Authorization: Bearer <管理员Token>" \
  -H "Content-Type: application/json" \
  -d '{
    "file_names": [
      "alice427dcd@pnj.sixthirtydance.org.json",
      "antigravity-artemisultra662155@bngg.dsckck.com.json"
    ],
    "dry_run": true
  }'
```

确认后执行真实删除：

```bash
curl -X POST "http://127.0.0.1:8080/api/v1/admin/accounts/delete-by-file-names" \
  -H "Authorization: Bearer <管理员Token>" \
  -H "Content-Type: application/json" \
  -d '{
    "file_names": [
      "alice427dcd@pnj.sixthirtydance.org.json",
      "antigravity-artemisultra662155@bngg.dsckck.com.json"
    ]
  }'
```

### 6.6 返回示例

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "requested_files": 2,
    "matched_files": 2,
    "deleted_accounts": 2,
    "not_found_files": 0,
    "dry_run": false,
    "results": [
      {
        "file_name": "alice427dcd@pnj.sixthirtydance.org.json",
        "platform": "openai",
        "type": "oauth",
        "candidate_names": [
          "codex-alice427dcd@pnj.sixthirtydance.org"
        ],
        "matched_account_ids": [101],
        "deleted_account_ids": [101]
      },
      {
        "file_name": "antigravity-artemisultra662155@bngg.dsckck.com.json",
        "platform": "antigravity",
        "type": "oauth",
        "candidate_names": [
          "antigravity-artemisultra662155@bngg.dsckck.com"
        ],
        "matched_account_ids": [202],
        "deleted_account_ids": [202]
      }
    ]
  }
}
```

## 7. 本地脚本调用方式

仓库内已经提供一个现成脚本：

```bash
python tools/upload_sub2api_credentials.py \
  --base-url "http://127.0.0.1:8080" \
  --token "<管理员Token>" \
  --source "凭证文件或目录"
```

### 7.1 只上传

原始凭证文件默认走 `replace-by-file-names`，即“覆盖上传”。

```bash
python tools/upload_sub2api_credentials.py \
  --base-url "http://127.0.0.1:8080" \
  --token "<管理员Token>" \
  --source "D:\github\Wei-Shaw\sub2api\tools\alice427dcd@pnj.sixthirtydance.org.json" \
           "D:\github\Wei-Shaw\sub2api\tools\antigravity-artemisultra662155@bngg.dsckck.com.json"
```

### 7.2 先删后传

```bash
python tools/upload_sub2api_credentials.py \
  --base-url "http://127.0.0.1:8080" \
  --token "<管理员Token>" \
  --source "D:\github\Wei-Shaw\sub2api\tools\alice427dcd@pnj.sixthirtydance.org.json" \
           "D:\github\Wei-Shaw\sub2api\tools\antigravity-artemisultra662155@bngg.dsckck.com.json" \
  --delete-before-upload
```

### 7.3 只删不传

```bash
python tools/upload_sub2api_credentials.py \
  --base-url "http://127.0.0.1:8080" \
  --token "<管理员Token>" \
  --source "D:\github\Wei-Shaw\sub2api\tools\alice427dcd@pnj.sixthirtydance.org.json" \
           "D:\github\Wei-Shaw\sub2api\tools\antigravity-artemisultra662155@bngg.dsckck.com.json" \
  --delete-only
```
