"use client";

import { motion } from "motion/react";
import { LoaderCircle, Pencil, Trash2 } from "lucide-react";
import { useActionState, useState, useTransition } from "react";

import { removeLink, saveLink, type ActionResult } from "@/app/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { TYPE_LABELS } from "@/lib/format";
import { CONTENT_TYPES, type ContentType } from "@/lib/types";

interface Props {
  linkId: string;
  note: string | null;
  tags: string[];
  contentType: ContentType;
}

const IDLE: ActionResult = { ok: false };

const labelClass = "text-xs font-medium text-muted-foreground";

export function LinkEditor({ linkId, note, tags, contentType }: Props) {
  const [editing, setEditing] = useState(false);
  const [deleteError, setDeleteError] = useState<string>();
  const [deleting, startDelete] = useTransition();
  const [result, formAction, saving] = useActionState(
    async (previous: ActionResult, form: FormData) => {
      const outcome = await saveLink(linkId, previous, form);
      if (outcome.ok) setEditing(false);
      return outcome;
    },
    IDLE,
  );

  function handleDelete() {
    if (!window.confirm("Delete this link? This can't be undone.")) return;
    startDelete(async () => {
      const outcome = await removeLink(linkId);
      setDeleteError(outcome.ok ? undefined : outcome.error);
    });
  }

  if (!editing) {
    return (
      <div className="flex items-center gap-0.5">
        {deleteError && <span className="mr-1 text-xs text-destructive">{deleteError}</span>}
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => setEditing(true)}
          aria-label="Edit link"
          title="Edit"
          className="text-muted-foreground"
        >
          <Pencil />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={handleDelete}
          disabled={deleting}
          aria-label={deleting ? "Deleting link" : "Delete link"}
          title="Delete"
          className="text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
        >
          {deleting ? <LoaderCircle className="animate-spin" /> : <Trash2 />}
        </Button>
      </div>
    );
  }

  const noteId = `note-${linkId}`;
  const tagsId = `tags-${linkId}`;

  return (
    <motion.form
      action={formAction}
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      className="flex w-full flex-col gap-3"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={noteId} className={labelClass}>
          Note
        </Label>
        <Textarea id={noteId} name="note" defaultValue={note ?? ""} rows={3} autoFocus />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={tagsId} className={labelClass}>
          Tags (comma-separated)
        </Label>
        <Input id={tagsId} name="tags" defaultValue={tags.join(", ")} placeholder="react, tools" />
      </div>
      <div className="flex flex-col gap-1.5">
        <span aria-hidden className={labelClass}>
          Type
        </span>
        <Select name="content_type" items={TYPE_LABELS} defaultValue={contentType}>
          <SelectTrigger aria-label="Type" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CONTENT_TYPES.map((type) => (
              <SelectItem key={type} value={type}>
                {TYPE_LABELS[type]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {result.error && <p className="text-xs text-destructive">{result.error}</p>}
      <div className="flex justify-end gap-2">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setEditing(false)}
          disabled={saving}
        >
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={saving}>
          {saving && <LoaderCircle data-icon="inline-start" className="animate-spin" />}
          {saving ? "Saving…" : "Save"}
        </Button>
      </div>
    </motion.form>
  );
}
