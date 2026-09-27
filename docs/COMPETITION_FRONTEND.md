# 参赛前端：人体地图与检查规划

实现日期：2026-09-21。分支：`feat/competition-body-ui`。

## 页面与功能

- `/competition`：独立于旧后台布局的人体地图、智能导入、缺项对话提示、只读信息核对。确认成功后才点亮；点亮表示有相关已确认资料，不表示疾病状态。
- `/competition/system/heart`、`metabolic`、`kidney`：三个系统的相关指标、历史时间线；只有心血管展示 PREVENT 长期风险及无法计算原因。
- `/competition/plan/heart`、`metabolic`、`kidney`：器官放大后转入带医生引导形象的系统规划。
- `/competition/plan/all`：全部建议汇总、保存报告、打印/PDF、已保存报告回看。首页和每个系统规划均可进入。

没有用户可见的 JSON 导入/导出、原文依据、手动编辑表格或体验示例入口。建议保留真实后端原因、明确时间及来源。没有专项建议时不显示“无需检查”。

人体、心脏、肾脏和医生为本次生成的原创展示素材；血糖使用抽象血滴，不把代谢功能解释成胰腺诊断。所有插图仅为导航/展示示意。

## 已接入与待接入的边界

已接入现有本地 API：模型状态、extract、confirm、assess、报告保存、报告列表和加载。计算和建议均来自真实后端，不在浏览器内伪造结果。

当前对话支持上传/粘贴、展示缺项、补充文字后重新提取、用户确认。新一轮确认替换当前工作档案，已保存快照不受影响。对话管理后端尚未交付，不能把这个前端称为完整对话式档案管理：逐条修改/删除/撤销、跨次报告合并、持久会话与操作版本控制仍按王天一任务书推进。界面公开说明能力边界；常见修改/删除指令明确告知未执行，不以聊天文字冒充数据库成功。

当前报告以 sessionStorage 保持当前标签页内刷新/路由连续性，关闭标签页后不保证保留。保存到后端的报告可回看。未确认上传文件和对话尚未持久化，刷新前应完成核对。不得将此机制当成王天一任务书要求的会话持久化。

后续由王天一交付契约，替换 ImportPanel 内提取编排部分；陈子正负责前端接入。数据适配与系统映射在 `frontend/components/competition/domain.ts`，旧 API 保留兼容，不修改 PREVENT 或指南规则。

## 启动与预览

依赖安装和后端启动沿用 README。常规合并部署后仍通过 `start-competition.cmd` 访问 3030。

本次隔离预览目录：`D:/junior_fall/SRTP/InsightCheck-competition-ui`。复用原项目已启动的 8000 后端和 Ollama，前端运行在 http://127.0.0.1:3040/competition 。

在该目录的 frontend 中运行 `npm run build`，然后 `npm run start -- --hostname 127.0.0.1 --port 3040` 即可启动。终端前台启动时 Ctrl+C 结束。源码修改后需要重新构建并重启生产预览。

## 验证

- ESLint、TypeScript、正式构建通过。
- 前端 5 项测试通过，包括系统资料覆盖、分系统建议隔离、整体去重和临床转介不丢失。
- 浏览器使用明确标为人工构造的文字资料，实测真实本地模型识别 → 核对 → 3/3 点亮 → 三系统详情和各自规划 → 四项整体建议 → 保存 → 刷新恢复 → 后端报告回看。
- 390px 窄屏检查无横向溢出，支持减少动画偏好及键盘操作。
- 打印使用浏览器原生打印与 A4 打印样式；内嵌浏览器最终 PDF 保存仍未完成验收，不能声称 PDF 成品已验证。
- 本次保存一条人工构造测试报告“体检档案 · 2026-09-21”，供流程验收，不是临床效果证据。没有使用真实患者资料。

## 图片来源与生成说明

风格参考：Humedix+ EHR Health Record Dashboard（https://dribbble.com/shots/27102614-Humedix-EHR-Health-Record-Dashboard）。只参考写实医学渲染与柔和材质，没有复制原图。

使用内置 image_gen 生成；素材已保存在仓库 `frontend/public/competition/anatomy.png` 与 `medical-atlas.png`，无外部图片请求。器官/医生三联图用 CSS 定位显示，无额外模型或运行依赖。

人体生成提示词：

> Create an original production website asset: a single full-body medical anatomical human muscular-system illustration, front orthographic view, from complete head to soles with small margins, adult anatomically neutral male medical teaching mannequin, arms slightly away from torso palms forward. Highly polished realistic 3D medical atlas rendering, fine individually sculpted muscle fibers, ivory tendons, softly desaturated terracotta salmon musculature, warm beige bone accents. Clean non-gory medical educational anatomy, no blood wounds or genitals, pelvis covered in smooth anatomical muscle surface. Accurate symmetrical proportions. Premium healthcare dashboard aesthetic, soft studio lighting and ambient occlusion, isolated on pure flat white background. No text, labels, frame, UI, symbols, ground platform, shadows outside figure. Tall portrait asset. Keep hands and feet fully visible. This will be a large interactive body map inside a warm white health dashboard.

器官/医生生成提示词：

> Create a production asset sheet for a premium medical web app. Wide landscape image EXACTLY three equal square panels side by side on uniform pure white background, no borders, no text, no labels. Left panel: a single detailed anatomically plausible human heart, upright anterior view with aorta, pulmonary vessels and fine coronary vessels, realistic polished medical atlas 3D rendering, warm terracotta red and soft pink, non-gory clean educational model. Middle panel: a matched pair of kidneys and thin ureters, anterior view, muted mauve pink, realistic detailed 3D medical atlas model with small central red/blue vessels, no other organs. Right panel: friendly fictional East Asian adult woman medical planning assistant wearing white coat with sage scrubs and stethoscope, waist-up portrait, holding beige clipboard, realistic softly lit 3D editorial portrait. All subjects fully inside their own equal-width panel with 12 percent white margin on each side. High-end soft studio illumination, accurate natural proportions, subtle ambient occlusion, white seamless backdrop, cohesive warm neutral colors. No dashboard or decorative icons. Output 3:1 landscape.
