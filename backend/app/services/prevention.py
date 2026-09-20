"""Screening planning is independent of PREVENT; every decision is traceable."""

from datetime import date, timedelta

from app.schemas.prevention import PreventionRequest
from app.services.prevent_equations import COEFFICIENTS, calculate, eligibility

SOURCES = {
    "ADA2026": {"title": "ADA 2026：糖尿病筛查（表 2.5）",
                "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC12690183/"},
    "USPSTF2021": {"title": "USPSTF 2021：成人血压筛查",
                   "url": "https://www.uspreventiveservicestaskforce.org/uspstf/"
                          "recommendation/hypertension-in-adults-screening"},
    "PREVENT": {"title": "AHA PREVENT：用途与输入范围",
                "url": "https://professional.heart.org/en/guidelines-and-statements/"
                       "about-prevent-calculator"},
    "KDIGO2024": {"title": "KDIGO 2024：肾病评估",
                  "url": "https://kdigo.org/guidelines/ckd-evaluation-and-management/"},
}


def anniversary(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def assess(request: PreventionRequest) -> dict:
    visits = sorted(request.visits, key=lambda v: v.date)
    current = visits[-1]
    as_of = request.as_of
    horizon = anniversary(as_of, 1)
    blockers = eligibility(current)
    if request.known_cvd:
        blockers.append("已有明确心血管疾病，不适用一级预防风险方程")
    if request.pregnant:
        blockers.append("妊娠场景超出本比赛版适用范围")
    if request.symptomatic:
        blockers.append("存在当前不适，应就医评估，不使用常规体检计划处理症状")
    # This is an explicit engineering freshness policy, not an AHA cutoff.
    if (as_of - current.date).days > 365:
        blockers.append("最新完整记录已超过 365 天：按平台资料时效策略先更新再评估")
    risks = None if blockers else calculate(current, request.sex)
    items = []

    def add(code, title, decision, reason, source, due=None, basis="指南规则"):
        items.append({"code": code, "title": title, "decision": decision, "reason": reason,
                      "source": source, "basis": basis,
                      "due_date": due.isoformat() if due else None,
                      "within_next_year": due <= horizon if due else None})

    if request.symptomatic or request.pregnant:
        add("clinical", "临床评估", "先由医生评估", blockers[-1], "PREVENT",
            basis="平台适用范围保护")
    else:
        glucose_visits = [v for v in visits if v.fasting_glucose is not None
                          or v.hba1c is not None]
        glucose = glucose_visits[-1] if glucose_visits else None
        # A previous confirmed abnormality cannot be erased by a missing later status.
        known_pre = any(v.glucose_status == "prediabetes" for v in visits)
        abnormal = glucose and (
            (glucose.hba1c is not None and glucose.hba1c >= 5.7)
            or (glucose.fasting_glucose is not None and glucose.fasting_glucose >= 5.6))
        if current.dm:
            add("glucose", "血糖 / HbA1c 随访", "纳入慢病随访",
                "已有糖尿病病史，应遵循现有治疗团队的监测安排，不能等到下一年度筛查。"
                "本系统不调整治疗或代定监测频率。", "ADA2026", as_of)
        elif abnormal and (glucose.glucose_status in ("normal", "unknown")
                           or (glucose.hba1c is not None and glucose.hba1c >= 6.5)
                           or (glucose.fasting_glucose is not None
                               and glucose.fasting_glucose >= 7)):
            add("glucose", "血糖结果复核", "先复核，不等待年度体检",
                "记录的数值与正常/未确认状态不一致；需核对空腹条件、单位及既有结论。"
                "此提示不确诊糖尿病或糖尿病前期。", "ADA2026", as_of)
        elif known_pre:
            last_test = glucose.date if glucose else as_of - timedelta(days=366)
            due = anniversary(last_test, 1)
            add("glucose", "血糖筛查（空腹血糖或 HbA1c）", "建议纳入未来一年",
                "既往已确认糖尿病前期，指南建议每年检测；两种检查由医生按情况选择，"
                "不默认要求重复做两项。", "ADA2026", max(due, as_of))
        elif glucose is None or glucose.glucose_status != "normal":
            add("glucose", "血糖筛查资料补齐", "需要补充/确认",
                "没有可用于安排复查间隔的已确认正常血糖记录；不能据此建议免检。",
                "ADA2026", as_of, "资料完整性规则")
        elif current.age >= 35:
            due = anniversary(glucose.date, 3)
            changed = (current.bmi - visits[0].bmi >= 2 if len(visits) > 1 else False)
            if changed:
                add("glucose", "血糖筛查间隔复核", "建议与医生讨论提前检查",
                    "BMI 较最早记录增加至少 2；平台用此阈值提示风险状态改变，"
                    "不是指南规定的诊断界值或固定复查周期。", "ADA2026", as_of,
                    "指南原则 + 平台变化提醒")
            else:
                add("glucose", "血糖筛查（空腹血糖或 HbA1c）",
                    "建议纳入未来一年" if due <= horizon else "暂不自动列入年度必查",
                    "依据已确认正常结果按 3 年基准安排；如出现症状、新风险或医生已有"
                    "更短随访要求，应提前检查。暂不列入不等于保证无需检查。",
                    "ADA2026", max(due, as_of))
        else:
            add("glucose", "血糖筛查风险因素核对", "由医生个体化确认",
                "年龄小于 35 岁，本版尚未收集完整家族史等提前筛查因素，"
                "不能自动作出无需筛查的结论。", "ADA2026")

        if current.bp_tx or current.sbp >= 130:
            add("bp", "血压复测与既有随访", "优先确认随访安排",
                "正在降压治疗或收缩压偏高；需要临床复测/随访，不能只安排年度筛查。",
                "USPSTF2021", as_of)
        elif current.age >= 40 or current.bmi >= 25:
            add("bp", "血压测量", "建议纳入未来一年",
                "年龄至少 40 岁或超重人群建议每年筛查血压。", "USPSTF2021",
                max(anniversary(current.date, 1), as_of))
        else:
            add("bp", "血压筛查间隔确认", "由医生个体化确认",
                "未收集舒张压及全部高风险因素，不能直接套用低风险人群较长间隔。",
                "USPSTF2021")
        add("lipids", "血脂及心血管预防讨论", "结合风险与既有医嘱确定",
            "将本次长期风险结果及血脂记录交由医生讨论；PREVENT 本身不规定"
            "血脂复查周期，也不自动要求心电图、CT 或超声。", "PREVENT")
        if current.egfr < 60 or current.dm:
            add("kidney", "肾功能及尿白蛋白评估", "建议与医生确认",
                "eGFR 降低或有糖尿病病史，建议核对肾脏评估与既有监测安排；"
                "单次 eGFR 不能确诊慢性肾病。", "KDIGO2024", as_of)

    trends = []
    for key, label, unit in [("sbp", "收缩压", "mmHg"), ("bmi", "BMI", "kg/m²"),
                              ("egfr", "eGFR", "mL/min/1.73m²"),
                              ("hba1c", "HbA1c", "%"),
                              ("fasting_glucose", "空腹血糖", "mmol/L")]:
        points = [{"date": v.date.isoformat(), "value": getattr(v, key)} for v in visits
                  if getattr(v, key) is not None]
        trends.append({"key": key, "label": label, "unit": unit, "points": points,
                       "change": round(points[-1]["value"] - points[0]["value"], 3)
                       if len(points) > 1 else None})
    return {
        "input": request.model_dump(mode="json"), "risk": risks, "blockers": blockers,
        "planning_window": [as_of.isoformat(), horizon.isoformat()],
        "recommendations": items, "trends": trends, "sources": SOURCES,
        "rules_version": "competition-screening-1.0", "upstream": COEFFICIENTS["revision"],
        "review_status": "待医学审核",
        "limitations": ["风险是未来 10/30 年概率，不是明年患病概率；各结局不可相加。",
                        "美国人群模型，尚未在中国或九华人群验证。",
                        "推荐规则独立于 PREVENT，未经过本地医学专家审核。",
                        "历史变化是描述性趋势，不代表病因或治疗效果。",
                        "比赛研究演示，不用于诊断、处方或独立医疗决策。"],
    }
