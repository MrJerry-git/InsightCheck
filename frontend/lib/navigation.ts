import type { LucideIcon } from "lucide-react";
import {
  BrainCircuit,
  ChartNoAxesCombined,
  ClipboardCheck,
  FileHeart,
  FileSearch,
  FlaskConical,
  LayoutDashboard,
  ListChecks,
  MessageCircle,
  ScanLine,
  ShieldCheck,
  Stethoscope,
  Users,
} from "lucide-react";

export type NavigationItem = {
  label: string;
  href: string;
  icon: LucideIcon;
};

export type NavigationGroup = {
  label: string;
  items: NavigationItem[];
};

export const navigationGroups: NavigationGroup[] = [
  {
    label: "总览",
    items: [{ label: "工作台", href: "/dashboard", icon: LayoutDashboard }],
  },
  {
    label: "健康档案",
    items: [
      { label: "受检者", href: "/patients", icon: Users },
      { label: "体检记录", href: "/health-records", icon: FileHeart },
      { label: "影像随访", href: "/imaging", icon: ScanLine },
      { label: "纵向趋势", href: "/trends", icon: ChartNoAxesCombined },
    ],
  },
  {
    label: "辅助分析",
    items: [
      { label: "风险分析", href: "/risk-analysis", icon: ShieldCheck },
      { label: "体检推荐", href: "/recommendations", icon: ClipboardCheck },
      { label: "方案报告", href: "/ai-report", icon: FileSearch },
      { label: "方案说明", href: "/ai-chat", icon: MessageCircle },
    ],
  },
  {
    label: "系统管理",
    items: [
      { label: "体检项目", href: "/admin/exam-items", icon: Stethoscope },
      { label: "医疗规则", href: "/admin/medical-rules", icon: ListChecks },
      { label: "模型版本", href: "/admin/models", icon: BrainCircuit },
    ],
  },
  {
    label: "演示",
    items: [{ label: "Demo", href: "/demo", icon: FlaskConical }],
  },
];

export const allNavigationPaths = navigationGroups.flatMap((group) =>
  group.items.map((item) => item.href),
);

