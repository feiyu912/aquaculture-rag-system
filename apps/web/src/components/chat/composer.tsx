"use client";

import * as React from "react";
import { ArrowUp, Loader2, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

export function Composer({
  value,
  onChange,
  species,
  onSpeciesChange,
  speciesOptions,
  isStreaming,
  onSend,
  onStop,
  disabled,
}: {
  value: string;
  onChange: (value: string) => void;
  species: string | null;
  onSpeciesChange: (value: string | null) => void;
  speciesOptions: string[];
  isStreaming: boolean;
  onSend: () => void;
  onStop: () => void;
  disabled?: boolean;
}) {
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);

  React.useEffect(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "0px";
    const next = Math.min(node.scrollHeight, 200);
    node.style.height = `${next}px`;
  }, [value]);

  const canSend = value.trim().length > 0 && !isStreaming && !disabled;

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      if (canSend) onSend();
    }
  };

  return (
    <div className="shrink-0 border-t border-border bg-background/80 px-4 pb-4 pt-3 backdrop-blur-md sm:px-6">
      <div className="mx-auto w-full max-w-[780px]">
        <div
          className={cn(
            "rounded-2xl border border-border bg-surface shadow-sm transition-[border-color,box-shadow] duration-200 ease-soft",
            "focus-within:border-primary-400 focus-within:ring-2 focus-within:ring-primary-500/12",
          )}
        >
          <textarea
            ref={textareaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
            disabled={disabled}
            placeholder="提出一个水产养殖问题，例如：中华绒螯蟹扣蟹池塘的溶解氧要求是什么？"
            aria-label="输入问题"
            className="block max-h-[200px] w-full resize-none bg-transparent px-4 pb-1 pt-3.5 text-[14.5px] leading-[1.7] text-foreground outline-none placeholder:text-subtle-foreground disabled:opacity-60"
          />

          <div className="flex items-center gap-2 px-2.5 pb-2.5 pt-1">
            <SpeciesSelect
              species={species}
              onSpeciesChange={onSpeciesChange}
              options={speciesOptions}
            />

            {isStreaming ? (
              <Button
                size="icon-sm"
                variant="secondary"
                onClick={onStop}
                className="ml-auto"
                aria-label="停止生成"
              >
                <Square className="size-3.5 fill-current" />
              </Button>
            ) : (
              <Button
                size="icon-sm"
                onClick={onSend}
                disabled={!canSend}
                className="ml-auto"
                aria-label="发送"
              >
                {isStreaming ? <Loader2 className="animate-spin" /> : <ArrowUp className="size-4" />}
              </Button>
            )}
          </div>
        </div>

        <p className="mt-2 text-center text-[11.5px] text-subtle-foreground">
          Enter 发送 · Shift + Enter 换行 · 回答仅基于知识库资料，重要决策请咨询专业人员
        </p>
      </div>
    </div>
  );
}

function SpeciesSelect({
  species,
  onSpeciesChange,
  options,
}: {
  species: string | null;
  onSpeciesChange: (value: string | null) => void;
  options: string[];
}) {
  return (
    <Select
      value={species ?? "auto"}
      onValueChange={(next) => onSpeciesChange(next === "auto" ? null : next)}
    >
      <SelectTrigger className="h-7 w-auto gap-1.5 rounded-md border-transparent bg-surface-muted px-2 text-[11.5px] shadow-none hover:bg-surface-inset">
        <SelectValue placeholder="品种" />
      </SelectTrigger>
      <SelectContent align="start">
        <SelectItem value="auto">自动识别品种</SelectItem>
        {options.map((option) => (
          <SelectItem key={option} value={option}>
            {option}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
