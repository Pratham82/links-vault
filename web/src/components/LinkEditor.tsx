"use client";

import { useActionState, useState, useTransition } from "react";

import { removeLink, saveLink, type ActionResult } from "@/app/actions";
import { TYPE_LABELS } from "@/lib/format";
import { CONTENT_TYPES, type ContentType } from "@/lib/types";

interface Props {
  linkId: string;
  note: string | null;
  tags: string[];
  contentType: ContentType;
}

const IDLE: ActionResult = { ok: false };

const inputClass =
  "w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-900";
const buttonClass =
  "rounded-md px-2.5 py-1 text-xs font-medium transition-colors disabled:opacity-50";

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
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => setEditing(true)}
          className={`${buttonClass} text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800`}
        >
          Edit
        </button>
        <button
          type="button"
          onClick={handleDelete}
          disabled={deleting}
          className={`${buttonClass} text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950`}
        >
          {deleting ? "Deleting…" : "Delete"}
        </button>
        {deleteError && <span className="text-xs text-red-600">{deleteError}</span>}
      </div>
    );
  }

  return (
    <form action={formAction} className="flex w-full flex-col gap-2">
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        Note
        <textarea name="note" defaultValue={note ?? ""} rows={3} className={inputClass} />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        Tags (comma-separated)
        <input
          name="tags"
          defaultValue={tags.join(", ")}
          placeholder="react, tools"
          className={inputClass}
        />
      </label>
      <label className="flex flex-col gap-1 text-xs font-medium text-zinc-500">
        Type
        <select name="content_type" defaultValue={contentType} className={inputClass}>
          {CONTENT_TYPES.map((type) => (
            <option key={type} value={type}>
              {TYPE_LABELS[type]}
            </option>
          ))}
        </select>
      </label>
      {result.error && <p className="text-xs text-red-600">{result.error}</p>}
      <div className="flex gap-2">
        <button
          type="submit"
          disabled={saving}
          className={`${buttonClass} bg-zinc-900 text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900 dark:hover:bg-zinc-300`}
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => setEditing(false)}
          disabled={saving}
          className={`${buttonClass} text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800`}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
