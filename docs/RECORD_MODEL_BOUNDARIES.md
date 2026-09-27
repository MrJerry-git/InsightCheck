# 档案、记录修订与对话草稿的身份边界（T02 复核补充）

本说明回答 T02 审核提出的问题：参赛版对话后端（PR #39）使用另一套 profile/draft 表，
它们与 ``patients``／``RecordRevision`` 之间是什么关系，联调时以谁为准。

## 一、三套数据各自负责什么

| 数据 | 表 | 归属字段 | 回答的问题 |
| --- | --- | --- | --- |
| 正式档案与已确认资料 | ``patients`` → ``health_checks`` → ``lab_metrics`` / ``imaging_exams`` / ``exam_histories``，病灶另走 ``lesion_tracks`` | ``patients.owner_account_id`` | 这个人确认后的检查、指标、影像与随访是什么 |
| 记录修订历史 | ``record_revisions``（``entity_type`` + ``entity_id`` + ``revision_no`` 唯一） | ``record_revisions.patient_id`` | 某条正式记录在什么时间、由谁、因为什么被改成什么样 |
| 对话草稿与会话 | ``profiles`` / ``profile_drafts`` / ``conversation_sessions`` / ``conversation_messages``（PR #39） | 会话绑定账号，档案归属该账号 | 用户正在核对中的草稿、追问与操作记录 |

三者的时间边界是**确认动作**：

1. 草稿阶段只写 ``profile_drafts``，``profiles.version``（已确认版本）不变；
   ``draft_version`` 属于草稿，不能代表已确认资料。
2. 用户确认后，服务端把已确认内容写进 ``patients``／``health_checks``／``lab_metrics`` 等正式表，
   并同时写入一条 ``record_revisions``（``source_kind`` 标记为导入/对话来源，``source_ref`` 指向会话与消息）。
3. 人体点亮、系统历史与规划一律读取正式表，不读草稿；草稿修订不进入 ``record_revisions``，
   因此草稿不会污染正式修订历史，正式表也不会因为草稿来回改动而产生噪声。

## 二、身份边界

* **人**由 ``patients`` 表示；``profiles`` 表示“一个工作区的档案容器”，二者不是同一张表，
  也不做自动合并。同名或相似说法必须由用户确认，禁止按姓名/年龄自动合并。
* 账号维度：``patients.owner_account_id`` 与 ``profiles``/会话的账号归属必须同时成立；
  T 系列与 #39 的路由都按账号过滤，跨账号不可读、不可写（T01 归属控制）。
* T02 新增的 ``GET /profiles/{id}/revisions`` 中的 ``{id}`` 是**患者档案 ID**（``patients.id``），
  与 #39 的 ``profiles`` 表不是同一实体；两者并存时以 URL 命名空间区分（T 系列在 ``/api/v1/profiles``，
  对话后端在 ``/api/v1/conversation``）。

## 三、迁移与合并顺序

* T 链迁移是单链：``e5b17c9a2d40``(T01) → ``c3d8f0a41b27``(参赛报告归属) → ``f2a7c4d10e88``(T02) → …
* PR #39 的 ``a7c3d5e91b02`` 以当时 main 的 ``e021a0b10001`` 为父节点。合并前必须
  把它改挂到 main 当时的 head，否则会出现两条 head，``alembic upgrade head`` 直接报错。
* 从现有 main 数据库升级的验证方式（不只跑 ``create_all``）：
  ``alembic upgrade head`` 于真实旧库执行，旧患者、检查、指标行保持可读并回填
  ``source_kind='manual'``、``value_type='numeric'``、``revision_no=1``；
  见 ``backend/tests/test_migrations.py::test_upgrade_from_existing_database_keeps_legacy_rows``。
