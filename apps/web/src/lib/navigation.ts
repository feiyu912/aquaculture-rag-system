import { Activity, BookOpenText, Library, MessageSquareText } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  /** Match nested routes too (e.g. /chat/anything). */
  matchPrefix?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/chat",
    label: "智能问答",
    description: "检索增强问答与引用溯源",
    icon: MessageSquareText,
  },
  {
    href: "/knowledge",
    label: "知识库",
    description: "文档上传、版本与解析状态",
    icon: Library,
  },
  {
    href: "/reader",
    label: "文献阅读",
    description: "PDF 原文与引用高亮定位",
    icon: BookOpenText,
  },
  {
    href: "/debug",
    label: "检索调试",
    description: "查询 IR、融合与重排链路",
    icon: Activity,
  },
];

export const APP_NAME = "Aqua RAG";
export const APP_SUBTITLE = "水产养殖知识问答系统";
