/**
 * Shared display labels for trust/provenance values.
 *
 * These labels are deliberately conservative: a machine check is not called
 * "expert review", and a program-seeded FAQ is not called "expert verified".
 */

export const DOC_STATUS_LABELS: Record<string, string> = {
  active: "已发布",
  staging: "待审核",
  failed: "处理失败",
  deleted: "已删除",
  processing: "处理中",
};

export const REVIEW_STATE_LABELS: Record<string, string> = {
  pass: "通过",
  warn: "有告警",
  fail: "未通过",
  pending: "待检查",
  rejected: "已拒绝",
  verified: "已核验",
  not_recorded: "未记录",
};

export const AUTHORITY_LABELS: Record<string, string> = {
  national_standard: "国家标准",
  industry_standard: "行业标准",
  local_standard: "地方标准",
  international: "国际资料",
  standard_draft: "征求意见稿",
  official_technical: "官方技术文件",
  local_guidance: "地方技术指导",
  peer_reviewed: "同行评议文献",
  historical: "历史规范",
  synthetic: "合成示例",
  unknown: "效力未标注",
};

export const DOCUMENT_TYPE_LABELS: Record<string, string> = {
  standard: "正式标准",
  standard_draft: "征求意见稿",
  technical_guidance: "技术指导",
  research: "论文/科研资料",
  synthetic: "合成示例",
  other: "其他/未分类",
};

export const MEDIA_TYPE_LABELS: Record<string, string> = {
  pdf: "PDF",
  html: "网页",
  web: "网页",
  faq: "FAQ",
};

export const DOC_STATUS_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  active: "success",
  staging: "warning",
  failed: "danger",
  deleted: "neutral",
  processing: "warning",
};

export const REVIEW_TONE: Record<string, "success" | "warning" | "danger" | "neutral"> = {
  pass: "success",
  verified: "success",
  warn: "warning",
  pending: "warning",
  fail: "danger",
  rejected: "danger",
  not_recorded: "neutral",
};

export const UNAVAILABLE_REASON_LABELS: Record<string, string> = {
  document_deleted: "来源文档已删除，原文不可访问",
  document_missing: "来源文档记录已不存在",
  version_missing: "引用版本已不存在",
  faq_missing: "FAQ 条目已删除",
  faq_not_verified: "FAQ 已被撤回或未通过核验",
  faq_support_invalid: "FAQ 的支撑文献已失效或不再发布",
  support_document_missing: "支撑文献记录不存在",
  support_document_deleted: "支撑文献已删除",
  support_version_missing: "支撑版本不存在",
  support_version_not_current: "支撑版本已被新版本替代",
  support_document_unverified: "支撑文献未发布",
};

export function unavailableReasonLabel(reason: string | null | undefined): string {
  if (!reason) return "来源不可访问";
  return UNAVAILABLE_REASON_LABELS[reason] ?? reason;
}
