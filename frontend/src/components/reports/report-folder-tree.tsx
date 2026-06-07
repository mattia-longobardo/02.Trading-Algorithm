"use client";

import { Folder, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ReportFolder } from "@/lib/types";

type FolderFilter = number | null | "ALL";

interface FolderRowProps {
  label: string;
  active: boolean;
  onClick: () => void;
  className?: string;
}

function FolderRow({ label, active, onClick, className }: FolderRowProps) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 rounded-lg px-3 py-1.5 text-left text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-(--color-accent) ${
        active
          ? "bg-(--color-panel) text-(--color-text)"
          : "text-(--color-muted) hover:bg-(--color-hover)"
      } ${className ?? ""}`}
    >
      <Folder className="size-4" />
      <span className="truncate">{label}</span>
    </button>
  );
}

interface FolderTreeProps {
  folders: ReportFolder[];
  activeId: FolderFilter;
  onSelect: (id: number) => void;
  onDelete: (f: ReportFolder) => void;
}

function FolderTree({ folders, activeId, onSelect, onDelete }: FolderTreeProps) {
  const byParent = new Map<number | null, ReportFolder[]>();
  for (const f of folders) {
    const key = f.parent_id ?? null;
    if (!byParent.has(key)) byParent.set(key, []);
    byParent.get(key)!.push(f);
  }
  for (const list of byParent.values()) {
    list.sort((a, b) => a.name.localeCompare(b.name));
  }

  function render(parentId: number | null, depth: number): React.ReactNode {
    const children = byParent.get(parentId) ?? [];
    return children.map((f) => (
      <div key={f.id}>
        <div className="flex items-center gap-1" style={{ paddingLeft: depth * 12 }}>
          <FolderRow
            className="flex-1"
            label={f.name}
            active={activeId === f.id}
            onClick={() => onSelect(f.id)}
          />
          <Button
            variant="ghost"
            size="icon"
            className="text-(--color-muted) hover:text-rose-400"
            onClick={() => onDelete(f)}
            aria-label={`Elimina cartella ${f.name}`}
          >
            <Trash2 className="size-3.5" />
          </Button>
        </div>
        {render(f.id, depth + 1)}
      </div>
    ));
  }

  return <>{render(null, 0)}</>;
}

export interface ReportFolderTreeProps {
  folders: ReportFolder[];
  selected: FolderFilter;
  onSelect: (id: FolderFilter) => void;
  onDeleteFolder: (f: ReportFolder) => void;
}

export function ReportFolderTree({
  folders,
  selected,
  onSelect,
  onDeleteFolder,
}: ReportFolderTreeProps) {
  return (
    <div className="space-y-1">
      <FolderRow
        label="Tutte"
        active={selected === "ALL"}
        onClick={() => onSelect("ALL")}
      />
      <FolderTree
        folders={folders}
        activeId={selected}
        onSelect={(id) => onSelect(id)}
        onDelete={onDeleteFolder}
      />
    </div>
  );
}
