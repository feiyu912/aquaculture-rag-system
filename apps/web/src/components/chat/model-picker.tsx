"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, Loader2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { useLlmConfig } from "@/hooks/use-management";
import { manageApi } from "@/lib/api/manage";

export function ModelPicker() {
  const { data: config } = useLlmConfig();
  const queryClient = useQueryClient();
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState("");
  const [saving, setSaving] = React.useState(false);

  if (!config?.switchable) return null;

  const submit = async (model: string) => {
    setSaving(true);
    try {
      const next = await manageApi.updateLlmModel(model.trim(), model.trim() !== "");
      await queryClient.invalidateQueries({ queryKey: ["llm-config"] });
      toast.success(
        next.override_model
          ? `模型已切换：${next.effective_model}，下一条提问生效`
          : "已恢复默认模型，下一条提问生效",
      );
      setOpen(false);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "模型切换失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setDraft(config.effective_model);
      }}
    >
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 px-2.5 text-[11.5px] font-medium"
          aria-label="回答模型"
        >
          <Bot className="size-3.5 text-subtle-foreground" />
          模型：{config.effective_model}
          <ChevronDown className="size-3 text-subtle-foreground" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>回答模型（热切换）</DialogTitle>
          <DialogDescription>
            保存即写入服务端并立即生效，无需重启。保存时会向网关发一次 1-token 试连来验证模型名；
            当前生效：<span className="font-medium text-foreground">{config.effective_model}</span>
            {config.override_model ? "（页面覆盖）" : "（服务端默认）"}
          </DialogDescription>
        </DialogHeader>
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="例如 deepseek-v4.1-flash"
          aria-label="模型名称"
          onKeyDown={(event) => {
            if (event.key === "Enter" && draft.trim() && draft.trim() !== config.effective_model) {
              void submit(draft);
            }
          }}
        />
        <DialogFooter className="gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={saving || !config.override_model}
            onClick={() => void submit("")}
          >
            恢复默认（{config.env_model}）
          </Button>
          <Button
            size="sm"
            disabled={saving || !draft.trim() || draft.trim() === config.effective_model}
            onClick={() => void submit(draft)}
          >
            {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
            保存并验证
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
