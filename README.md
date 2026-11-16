# 自然保护区季节调查完整性、覆盖与个体重识别证据数据服务

面向自然保护区研究人员的两类数据服务：

1. **覆盖与调查有效性数据服务**：按「站点—样区—日期」组装调查单元，
   逐项判断设备可用性、时间可信度、空间覆盖与素材判读是否满足规则册门槛，签发
   **有效调查 / 受限调查 / 未有效调查 / 待核**证书，并并列展示经历史校准的检测概率估计。
2. **野生动物个体重识别证据与样线统计纳入服务**：每张照片、足迹或人工观察先登记为独立观察，
   外观相似只产生候选关系，经专家裁定后才形成冻结的确认个体版本；样线统计账只纳入确认个体在
   合规样线—日期组合中的首次/重复捕获，照片数、候选数与统计个体数分别统计、互不混同。

> 服务只交付覆盖有效性数据与个体重识别证据链。它**不派发巡护任务、不预约人员器材、不创建执法/捕捉/资源调度动作**，
> 也**不改变动物管理、捕捉、放归或保护行动**，不把调查缺口转成行动指令。

---

## 1. 技术栈

| 层 | 技术 |
| --- | --- |
| 前端 | Vue 3.5 + TypeScript + Vue Router + Vite 7 |
| 后端 | FastAPI 0.163 + SQLAlchemy 2.1 + Shapely 2.2 |
| 数据库 | PostgreSQL 18（JSONB 存原始载荷 / 门槛快照 / 证书结论 / 重识别证据与冻结版本） |
| 测试 | pytest（33 个用例：15 个覆盖有效性 + 18 个个体重识别验收场景） |

## 2. 一键启动（Docker Compose）

```bash
cd <仓库根目录>
docker compose up --build
```

启动后：

- 前端：<http://localhost:8080>
- 后端 OpenAPI 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

首次启动时后端容器会等待 PostgreSQL 就绪，自动建表并写入演示种子数据
（1 个覆盖运行、9 个站点、27 个调查单元、536 条档案记录；以及 1 个重识别联合批次、
23 张鹿类观察、21 条候选关系、5 个确认个体与首版冻结样线统计账）。

停止：`docker compose down`；连同数据卷清理：`docker compose down -v`。

## 3. 本地开发（不使用 Docker）

运行时已在容器内预装（Python 3.12 / Node 22 / PostgreSQL 18），也可用本机同版本。

### 3.1 数据库

```bash
# 数据库账号 ccdev / ccdev，端口 5432
createdb -h 127.0.0.1 -U ccdev survey_integrity        # 开发库
createdb -h 127.0.0.1 -U ccdev survey_integrity_test   # 测试库（pytest 使用）
```

### 3.2 后端

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

export DATABASE_URL='postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity'
.venv/bin/python -m app.seed                # 建表 + 写入演示数据（可重复执行，已有数据则跳过）
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- API 根路径：`http://127.0.0.1:8000/api`
- Swagger UI：`http://127.0.0.1:8000/docs`
- OpenAPI JSON：`http://127.0.0.1:8000/openapi.json`

> 本项目为全栈应用（含业务前端页面），按任务约束同时提供可运行的 OpenAPI 3.x 文档与 Swagger UI，
> 便于接口对接与验收。

### 3.3 前端

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173 ，/api 代理到 http://127.0.0.1:8000
```

生产构建：`npm run build`（产物在 `frontend/dist`，可用任意静态服务器托管，`/api` 反代到后端）。

### 3.4 测试

```bash
cd backend
DATABASE_URL='postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity_test' \
  .venv/bin/python -m pytest -q
```

测试会重建测试库的 `public` schema 并写入种子数据，**不会影响开发库**。

## 4. 测试账号

| 账号 | 密码 | 角色 | 权限 |
| --- | --- | --- | --- |
| `yq.li` | `Survey#2026` | 研究人员 researcher | 组装运行、登记/撤回趋势引用、修订记录与判读、处置冲突、重新签发证书 |
| `m.cao` | `Audit#2026` | 审核员 auditor | 同上（用于复核类操作与审计） |
| `l.lin` | `View#2026` | 只读访客 viewer | 只读查看所有数据 |

## 5. 业务模型与判定口径

### 5.1 调查单元

覆盖组装器按 `站点 × 样区 × 调查日`（规则册 `schedule.survey_dates`）生成调查单元。
每个单元固定引用：站点版本、规则册版本、概率模型版本，并把四类门槛的判定与证据记录 id 一并留存。

### 5.2 四类门槛

| 门槛 | 判定要点 | 典型结论 |
| --- | --- | --- |
| `device` 设备可用性 | 心跳间隔、连续图像帧序列（`frame_seq` 跳号）、停机日志覆盖；未解释缺口 → **待核** | 帧缺失且停机日志未覆盖 → 设备待核 |
| `time` 时间可信度 | 设备时间与可信源偏差 vs 容差（120s）；**存在可验证校时关系**才可回算；迟到送达只记录不改事件时间 | 偏移超容差且无校时 → 未满足 |
| `space` 空间覆盖 | 巡护轨迹对规则册路线段的覆盖、进入缓冲区深度、**定位精度半径 vs 缓冲区宽度**；按事件时间的站点版本取边界 | 仅擦过缓冲边缘且精度 > 缓冲宽度 → 空间待核 |
| `reading` 素材判读 | 达置信门槛的判读数、待判读占比、互斥判读冲突 | 互斥且均低于门槛 → 保留冲突、判读待核 |

### 5.3 证书状态与用途

| 状态 | 含义 | 正式未发现结论 | 趋势输入 |
| --- | --- | --- | --- |
| 有效调查 `valid` | 四类门槛均通过且无未决冲突 | ✅ | ✅ |
| 受限调查 `restricted` | 主要门槛通过但存在受限项 | ❌ | ✅ |
| 未有效调查 `invalid` | 存在未满足门槛 | ❌ | ❌ |
| 待核 `pending` | 存在待核实证据 | ❌ | ❌ |
| 复审中 `under_review` | 判读修订改变出现判定后签发的复审版本 | ❌ | ❌（暂停新引用） |

证书快照（门槛判定 + 结论）在签发时深拷贝保存；后续重算不会改写已签发证书。
复审会**新增一个证书版本**并把旧证书标记为被替代，旧运行仍可看到原证书原貌。

### 5.4 规则证书 vs 概率估计

- **规则证书**：逐项门槛，可向监管人员解释；接近门槛的部分路线会被排除，样本更少。
- **概率估计**：`DET-LOGIT` 检测概率模型（logistic，特征为设备可用比例、路线覆盖、达门槛判读数、待判读比例、
  缓冲区内素材比例、精度是否可信），时间可信与无冲突是**门控特征**（不满足则覆盖值为 0）。
  结果带 80% 敏感区间、校准集切换（pivot 偏移）与阈值上浮敏感性。
- 概率结果**仅用于趋势研究**，界面与接口均标注「模型推算，不是已确认的实地覆盖」，
  接口 `purpose=trend_only`，不会写入证书用途。

### 5.5 七个验收场景（种子数据）

| 站点 | 场景 | 期望结果 |
| --- | --- | --- |
| `QSL-01` 青松岭主监测站 | 完整调查 + 可验证校时 + 迟到送达 | 有效调查，可用于正式未发现结论 |
| `QSL-02` 青松岭北梁相机站 | 有心跳但帧连续缺失，停机日志未覆盖 | 设备可用性**待核**，不判未出现 |
| `QSL-03` 青松岭西沟站 | 两来源互斥判读且均低于 0.70 | 判读**待核**，保留冲突 |
| `QSL-04` 青松岭东南站 | 待判读占比过高（薄判读） | 判读待核；概率估计偏低 |
| `YXG-01` 云溪沟西站 | 轨迹只擦过缓冲边缘，精度 40m > 缓冲 30m | 空间**待核** |
| `YXG-02` 云溪沟东站 | 迟到判读修订：未出现 → 出现 | 当前证书**复审中**，旧引用暂停，旧证书保留 |
| `YXG-03` 云溪沟下坝站 | 路线覆盖 60%（接近门槛 50%/目标 80%） | 受限调查；概率估计仍过阈值 → 样本取舍分歧 |
| `BHP-01` 北坡高寒相机站 | 设备时钟偏移 900s 且无可验证校时 | 时间**未满足** → 未有效调查 |
| `BHP-02` 北坡垭口迁移站 | 4/11 迁移边界与路线段变更 | 4/11 用 v1、4/12 用 v2，各自判定 |

### 5.6 个体重识别证据链（re-identification）

**数据链分层（照片数 ≠ 候选数 ≠ 统计个体数）：**

1. **独立观察 `ReidObservation`**：每张照片、足迹或人工观察单独登记，保留原始文件哈希、
   采集时间与接收时间、相机/样线位置、姿态质量、可见特征、设备校时与来源授权。
2. **来源簇 `ReidSourceCluster`**：同一连拍序列（burst）、同一原图的裁剪件（crop）、
   同文件哈希副本（duplicate_hash）只能归入同一来源簇；同簇素材不互成重识别候选，
   在同一样线—日期只计一次捕获。
3. **候选关系 `ReidCandidate`**：外观相似**只登记候选**，分别记录斑纹/伤痕特征相似度、
   时空可达性（按最大移动速度）、素材来源独立性与反证。候选状态：候选 / 确认 / 否决 /
   保留待补证 / 同级相反裁定待定 / 受否决约束封锁。
4. **专家决策 `ReidDecision`**：专家作出确认、否决或保留待补证，冻结当时采用的特征提取版本、
   位置版本、时间校正版本与理由（`frozen_versions` + `evidence_snapshot`）。
5. **确认个体与版本 `ReidIndividual` / `ReidIndividualVersion`**：只有确认边才能形成个体版本，
   版本冻结观察归属、来源簇、候选与决策引用；后续变化生成新版本，旧版本保留可还原。
6. **样线统计账 `ReidReportRun` / `ReidCaptureEntry`**：只把确认个体在合规样线—日期组合中的
   首次/重复捕获纳入；另列待核候选、否决关系、无法判读、季节窗口外、复审暂停、竞争冻结、
   同来源簇重复等排除桶。每次重算生成**新的冻结季报**，旧季报永不改写。

**关键规则：**

- **批次内联合候选 + 专家裁定**：`POST /api/reid/batches` 做联合搜索并产出若干一致划分
  （`ReidPartition`），得分最高的划分**不会自动进入统计**；专家可逐对裁定，也可整体采用划分。
- **搜索截断**：候选对超过上限时批次标记 `truncated`，记录已检查范围与未解决观察，不声称找到唯一划分。
- **全组一致性**：两对分别可达的观察传递合并后，若要求同一个体同一时刻出现在无法往返的两地，
  合并被拒绝（`transitive_spatiotemporal_conflict`）。
- **否决是硬约束**：被否决的同一个体关系在任何其他相似链上都不能绕过。
- **时间校正**：只重算可达性并**新建候选关系，绝不自动合并**；专家确认后才更新统计纳入；
  校时把观察推出季节窗口时，观察保留在档案但不再作为该季有效捕获。
- **并发裁定**：决策带乐观版本号 `expected_last_decision_id`，后提交且基于旧状态者被 409 拦截，
  须回到最新证据复核；同一观察不能贡献两个个体。
- **同级相反裁定**：两位同级专家给出相反结论时，候选冻结统计资格转 `adjudicating_pending`，
  相关个体版本转复审，观察保留但不进个体数，直到第三方证据或上级裁定（senior）收口。
- **竞争归属冻结 `ReidMembershipHold`**：一张照片已属个体 A 又被候选链主张属个体 B 时，
  先冻结两端重复捕获归属，不能同时贡献两条轨迹。
- **变动监测 `ReidReviewEvent`**：关键照片授权撤回、哈希不一致或位置版本修订时，当前个体版本
  转复审中；旧季报保持当时统计版本，新统计暂停纳入该个体；复审可沿用、修订（拆分）或撤销资格。
- **确认后拆分**：拆分按新归属重算受影响的首次/重复捕获，不把原捕获次数复制给每个新个体，
  无关样线统计不失效。

## 6. 验证方式（均已实际执行）

### 6.1 自动化测试

```bash
cd backend
DATABASE_URL='postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/survey_integrity_test' \
  .venv/bin/python -m pytest -q
# 33 passed
```
覆盖：

- `tests/test_scenarios.py`：7 个验收场景 + 校时放行 + 引用用途限制 + 回溯链完整性 + 无派工动作断言
- `tests/test_revisions.py`：判读修订触发复审与新证书版本、档案记录修订保留哈希链、
  单元证据全链可回溯、重算运行不改变旧证书
- `tests/test_reid.py`（18 个个体重识别场景）：
  - 照片/候选/统计个体三个口径分离；裁剪副本与连拍只作同一来源簇、单次捕获
  - 被否决关系不可在另一条链绕过；传递合并的全组时空一致性拦截
  - 时间校正只新建候选、专家确认后才入统；校时跨季节窗口后排除捕获但保留档案
  - 乐观并发拦截过期裁定；同级相反裁定冻结资格并转上级/第三方收口
  - 竞争归属冻结，一张照片不贡献两条轨迹；冻结在否决后解除
  - 授权撤回 / 哈希不一致 / 位置修订触发复审，旧季报可还原；复审可沿用或撤销
  - 确认后拆分重算捕获、不复制次数、无关样线不失效
  - 联合划分不自动采用最高分；搜索截断记录已查范围与未解决观察
  - 季报与观察双向溯源链完整；重识别接口无任何派工/调度动作

### 6.2 前端构建与类型检查（本次已实际执行）

```bash
cd frontend
npm run build            # vue-tsc 类型检查 0 error，vite 构建成功，含 ReidWorkspace / ReidTrace 产物
```

### 6.3 端到端界面验证

覆盖域（站点总览、单元详情、冲突、趋势、回溯等 8 页）的 headless Chromium 逐页截图核对为基线交付时的验证记录，本环境未重复执行。

本次新增的「重识别工作区 / 重识别溯源」两个页面在本环境实际执行的验证是：TypeScript 类型检查与生产构建通过、
后端 28 个 `/api/reid` 接口经 HTTP 冒烟与 18 个 pytest 场景覆盖；未在本环境运行浏览器截图。

### 6.4 API 冒烟

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"yq.li","password":"Survey#2026"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

curl -s http://127.0.0.1:8000/api/runs -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/runs/1/overview -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/units/1/trace -H "Authorization: Bearer $TOKEN"

# 个体重识别证据链
curl -s http://127.0.0.1:8000/api/reid/observations -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/reid/batches -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/reid/candidates -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/reid/individuals -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/reid/report-runs -H "Authorization: Bearer $TOKEN"
```

已实际执行的 HTTP 冒烟确认：健康检查返回 `survey-integrity-and-reid`；登录后可读取
23 张重识别观察、1 个联合批次（completed）、5 个活跃确认个体与冻结季报（统计个体数 5）。

## 7. 界面

| 页面 | 说明 |
| --- | --- |
| 站点覆盖总览 | 站点 × 调查日矩阵、门槛分布、需关注单元、最近数据活动 |
| 单元详情 | 规则证书 vs 概率估计并列；四门槛证据；原始证据表；证书历史；审计；引用登记 |
| 规则证书 vs 概率估计 | 逐单元并列对照、分歧分类、阈值敏感性、单单元敏感度复算 |
| 趋势输入清单 | 按用途/状态筛选引用，显示引用时证书快照与概率区间 |
| 单元回溯链 | 原始事件 → 覆盖条件 → 规则/模型/站点版本 → 证书 → 趋势引用 |
| 观测档案 | 类型/站点/编号检索，原始载荷、哈希、修订历史、载荷修订 |
| 判读冲突 | 未决冲突的来源、置信度、处置记录 |
| 样区规则册与模型 | 规则册四类门槛、路线段、海拔带；模型校准集、权重、阈值复核 |
| 重识别工作区 | 观察与来源簇登记、联合批次/候选/划分/专家裁定、确认个体拆分、样线统计账、复审与归属冻结 |
| 重识别溯源 | 从观察或季报个体数量回到原始素材、候选关系、来源独立性、专家决策、冻结版本、捕获纳入与复审历史 |

## 8. 主要 API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/login` | 登录，返回 HMAC 签名令牌 |
| GET | `/api/runs` | 运行列表（含状态计数、未决冲突数） |
| POST | `/api/runs` | 按规则册/模型/站点组装新运行 |
| GET | `/api/runs/{id}/overview` | 总览：矩阵、门槛分布、对照行、活动 |
| GET | `/api/runs/{id}/units` | 单元列表（可按站点/证书状态/门槛过滤） |
| GET | `/api/units/{id}` | 单元详情：门槛、证书、概率、证据、冲突、审计 |
| GET | `/api/units/{id}/trace` | 可回查的五段回溯链 |
| GET | `/api/units/{id}/records` | 单元引用的原始记录（含修订） |
| POST | `/api/units/{id}/trend-references` | 登记 `absence` / `trend` 引用（含用途校验） |
| POST | `/api/units/{id}/certificates/reissue` | 复审后重新签发证书 |
| GET/POST | `/api/records`、`/api/records/{id}/revisions` | 档案检索、载荷修订（哈希 + 修订号） |
| POST | `/api/determinations`、`/api/determinations/{id}/revisions` | 判读新增/修订（触发复审） |
| GET/POST | `/api/conflicts`、`/api/conflicts/{id}/resolve` | 冲突列表与处置 |
| GET/POST | `/api/trend-references`、`/api/trend-references/{id}/revoke` | 引用列表与撤回 |
| POST | `/api/probability/models/{id}/evaluate` | 概率复算（可选校准集偏移，只读不签署） |
| GET | `/api/probability/models/{id}/threshold-sensitivity` | 阈值敏感性 |
| GET/POST | `/api/reid/feature-versions`、`/location-versions`、`/time-corrections` | 特征/位置/校时版本登记与列表 |
| GET/POST | `/api/reid/observations`、`/api/reid/observations/{id}` | 独立观察登记（自动来源簇归并）与检索 |
| POST | `/api/reid/observations/{id}/time-correction` | 应用校时（只新建候选，不自动合并） |
| POST | `/api/reid/observations/{id}/withdraw`、`/hash-mismatch`、`/location-revision` | 授权撤回 / 哈希不一致 / 位置修订（触发复审） |
| GET | `/api/reid/observations/{id}/trace` | 单张观察的完整重识别溯源链 |
| POST/GET | `/api/reid/batches`、`/api/reid/batches/{id}` | 批次内联合候选搜索与一致划分（含截断范围） |
| GET | `/api/reid/candidates`、`/api/reid/candidates/{id}` | 候选关系（特征/可达性/反证/决策） |
| POST | `/api/reid/candidates/{id}/decisions` | 专家确认/否决/保留（乐观并发 + 同级冲突冻结） |
| POST | `/api/reid/partitions/{id}/adopt` | 整体裁定采用一个划分（不自动取最高分） |
| GET/POST | `/api/reid/individuals`、`/api/reid/individuals/{id}/split` | 确认个体版本与确认后拆分 |
| GET/POST | `/api/reid/adjudications/{id}/resolve` | 同级相反裁定的第三方/上级收口 |
| GET/POST | `/api/reid/reviews/{id}/resolve` | 复审沿用/修订/撤销 |
| GET | `/api/reid/membership-holds` | 竞争归属冻结清单 |
| POST/GET | `/api/reid/report-runs`、`/api/reid/report-runs/{id}`、`/trace` | 冻结样线统计账、捕获条目与季报溯源 |
| GET | `/api/rulebooks`、`/api/models`、`/api/stations`、`/api/zones`、`/api/audit` | 规则册、模型、站点、样区、审计 |

## 9. 目录结构

```
backend/
  app/
    main.py            # FastAPI 应用与路由装配
    models.py          # 覆盖域 15 张表 + 重识别域 16 张表
    coverage.py        # 覆盖组装器：四类门槛判定与证据留存
    certificates.py    # 有效性裁定：状态、用途、复审版本
    probability.py     # 检测概率模型（含门控特征与敏感区间）
    services.py        # 组装运行、记录/判读修订、引用、冲突处置、重签发
    reid.py            # 个体重识别核心：来源簇、候选/划分搜索、裁定、捕获账、复审、溯源
    reid_serializers.py # 重识别响应序列化
    reid_seed.py       # 重识别演示种子（伤鹿双样线、裁剪、互斥、校时、竞争、同级冲突等）
    seed.py            # 确定性种子数据（覆盖 7 场景 + 调用 reid_seed）
    routers/           # auth / catalog / surveys / records / probability / reid
  tests/               # 33 个 pytest 用例（含 test_reid.py 18 个重识别场景）
frontend/
  src/views/           # 覆盖域 8 个页面 + 重识别工作区/溯源 2 个页面
  src/components/reid/ # 观察、候选裁定、统计账三个重识别分区组件
docker-compose.yml     # db + backend + frontend 一键启动
```

## 10. 数据与合规说明

- 数据库中的 `ccdev` 账号仅用于隔离开发/测试，不作为生产配置。
- 所有时间以保护区当地时区（UTC+8）解释、UTC 存储；时间校准关系仅在有 `verified: true` 且落在
  有效区间内时才用于回算事件时间。
- 服务端不包含任何派工、预约、执法、捕捉或资源调度接口；测试 `test_service_emits_no_dispatch_actions`
  会校验 OpenAPI 路径与总览响应中不出现相关动作。
- 个体重识别只产出证据链、专家裁定与样线统计纳入数据，**不改变动物管理、捕捉、放归或保护行动**；
  外观相似不自动合并、时间校正不自动入统、得分最高划分不自动采用，所有统计个体均需专家确认。
- 季报运行一经冻结不再改写；授权撤回、哈希不一致、位置修订等只让新版本转复审，
  旧季报始终可还原其当时采用的分组与冻结版本。
