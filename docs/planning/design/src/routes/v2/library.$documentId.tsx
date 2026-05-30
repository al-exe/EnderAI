import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { createFileRoute, Link } from "@tanstack/react-router"
import {
  ArrowLeft,
  Bold,
  Eye,
  Folder,
  Heading1,
  Heading2,
  Heading3,
  Italic,
  Link as LinkIcon,
  Pencil,
  Pilcrow,
  Search,
  Share2,
  Star,
  Strikethrough,
  X,
} from "lucide-react"
import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import {
  type OrganizationMemberPublic,
  readMyOrganization,
} from "@/api/organizations"
import {
  favoriteV2Document,
  readV2Document,
  readV2DocumentFolders,
  readV2DocumentShares,
  replaceV2DocumentShares,
  unfavoriteV2Document,
  updateV2Document,
  type V2DocumentDetailsSection,
  type V2DocumentFolderPublic,
  type V2DocumentParagraph,
  type V2DocumentPublic,
  type V2DocumentSharePermission,
  type V2DocumentSharePublic,
  type V2DocumentUpdate,
} from "@/api/v2Documents"
import { useDemoMode } from "@/components/demo-mode-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  FolderCreateDialog,
  FolderPickerDropdown,
} from "@/components/V2/Library/FolderControls"
import useAuth from "@/hooks/useAuth"
import useCustomToast from "@/hooks/useCustomToast"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/v2/library/$documentId")({
  component: TaskforceDocumentDetail,
  head: () => ({
    meta: [
      {
        title: "Taskforce | Document",
      },
    ],
  }),
})

type ViewMode = "summary" | "details" | "split"

type AnchorPick = {
  paragraphIndex: number
  segmentIndex: number
  start: number
  end: number
  text: string
}

type DetailsPick = {
  sectionIndex: number
  start: number
  end: number
  text: string
}

type EditableDoc = {
  title: string
  description: string
  human_summary: string
  ai_generated_summary: string
  folder_id: string | null
  details_file_name: string
  main_body: V2DocumentParagraph[]
  details_markdown_sections: V2DocumentDetailsSection[]
}

type ShareDraft = Record<string, V2DocumentSharePermission>

function toEditable(document: V2DocumentPublic): EditableDoc {
  return {
    title: document.title,
    description: document.description,
    human_summary: document.human_summary,
    ai_generated_summary: document.ai_generated_summary,
    folder_id: document.folder_id ?? null,
    details_file_name: document.details_file_name,
    main_body: document.main_body.map((p) => ({
      segments: p.segments.map((s) => ({ ...s })),
    })),
    details_markdown_sections: document.details_markdown_sections.map((s) => ({
      ...s,
    })),
  }
}

function toUpdatePayload(edit: EditableDoc): V2DocumentUpdate {
  return {
    title: edit.title.trim(),
    description: edit.description,
    human_summary: edit.human_summary,
    ai_generated_summary: edit.ai_generated_summary,
    folder_id: edit.folder_id,
    details_file_name: edit.details_file_name,
    main_body: edit.main_body,
    details_markdown_sections: edit.details_markdown_sections,
  }
}

function formatDateOnly(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value))
}

function shortAnchorId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `evidence-${crypto.randomUUID().slice(0, 8)}`
  }
  return `evidence-${Math.random().toString(36).slice(2, 10)}`
}

function getOffsetWithin(
  root: Node,
  target: Node,
  targetOffset: number,
): number {
  if (!root.contains(target)) return -1
  let offset = 0
  const walker = window.document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  let node = walker.nextNode()
  while (node) {
    if (node === target) {
      return offset + targetOffset
    }
    offset += node.textContent?.length ?? 0
    node = walker.nextNode()
  }
  return -1
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;")
}

function renderInlineMarkdown(text: string, keyPrefix = "inline"): ReactNode[] {
  const nodes: ReactNode[] = []
  const pattern = /\*\*([^*]+)\*\*|~~([^~]+)~~|\*([^*]+)\*/g
  let cursor = 0
  let index = 0

  for (const match of text.matchAll(pattern)) {
    const matchIndex = match.index ?? 0
    if (matchIndex > cursor) {
      nodes.push(text.slice(cursor, matchIndex))
    }
    if (match[1]) {
      nodes.push(
        <strong key={`${keyPrefix}-strong-${index++}`}>
          {renderInlineMarkdown(match[1], `${keyPrefix}-strong-${index}`)}
        </strong>,
      )
    } else if (match[2]) {
      nodes.push(
        <s key={`${keyPrefix}-strike-${index++}`}>
          {renderInlineMarkdown(match[2], `${keyPrefix}-strike-${index}`)}
        </s>,
      )
    } else if (match[3]) {
      nodes.push(
        <em key={`${keyPrefix}-em-${index++}`}>
          {renderInlineMarkdown(match[3], `${keyPrefix}-em-${index}`)}
        </em>,
      )
    }
    cursor = matchIndex + match[0].length
  }

  if (cursor < text.length) {
    nodes.push(text.slice(cursor))
  }
  return nodes
}

function inlineMarkdownToHtml(text: string): string {
  return escapeHtml(text)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/~~([^~]+)~~/g, "<s>$1</s>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
}

function markdownToHtml(markdown: string): string {
  const blocks = markdown.trim() ? markdown.split(/\n{2,}/) : [""]

  return blocks
    .map((block) => {
      const trimmed = block.trim()
      const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed)
      if (heading) {
        const level = heading[1].length
        return `<h${level}>${inlineMarkdownToHtml(heading[2])}</h${level}>`
      }
      const lines = block.split("\n").map(inlineMarkdownToHtml).join("<br>")
      return `<p>${lines || "<br>"}</p>`
    })
    .join("")
}

function nodeToMarkdown(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) {
    return node.textContent ?? ""
  }
  if (!(node instanceof HTMLElement)) {
    return Array.from(node.childNodes).map(nodeToMarkdown).join("")
  }

  const children = Array.from(node.childNodes).map(nodeToMarkdown).join("")
  const tagName = node.tagName.toLowerCase()
  if (tagName === "strong" || tagName === "b") return `**${children}**`
  if (tagName === "em" || tagName === "i") return `*${children}*`
  if (tagName === "s" || tagName === "strike" || tagName === "del") {
    return `~~${children}~~`
  }
  if (tagName === "br") return "\n"
  if (tagName === "h1") return `# ${children}\n\n`
  if (tagName === "h2") return `## ${children}\n\n`
  if (tagName === "h3") return `### ${children}\n\n`
  if (tagName === "p" || tagName === "div") return `${children}\n\n`
  return children
}

function htmlToMarkdown(html: string): string {
  const template = window.document.createElement("template")
  template.innerHTML = html
  return Array.from(template.content.childNodes)
    .map(nodeToMarkdown)
    .join("")
    .replace(/\n{3,}/g, "\n\n")
    .trim()
}

function MarkdownBlocks({
  markdown,
  className,
}: {
  markdown: string
  className?: string
}) {
  const blocks = markdown.trim() ? markdown.split(/\n{2,}/) : [markdown]

  return (
    <div className={cn("space-y-4", className)}>
      {blocks.map((block, index) => {
        const trimmed = block.trim()
        const heading = /^(#{1,3})\s+(.+)$/.exec(trimmed)
        if (heading) {
          const level = heading[1].length
          const HeadingTag = `h${level}` as "h1" | "h2" | "h3"
          return (
            <HeadingTag
              key={`${trimmed}-${index}`}
              className={cn(
                "font-semibold tracking-tight text-foreground",
                level === 1 && "text-3xl",
                level === 2 && "text-2xl",
                level === 3 && "text-xl",
              )}
            >
              {renderInlineMarkdown(heading[2], `heading-${index}`)}
            </HeadingTag>
          )
        }

        const lines = block.split("\n")
        return (
          <p key={`${trimmed}-${index}`} className="whitespace-pre-wrap">
            {lines.map((line, lineIndex) => (
              <span key={`${line}-${lineIndex}`}>
                {lineIndex > 0 && <br />}
                {renderInlineMarkdown(line, `paragraph-${index}-${lineIndex}`)}
              </span>
            ))}
          </p>
        )
      })}
    </div>
  )
}

type RichCommand =
  | { icon: typeof Bold; label: string; command: "bold" }
  | { icon: typeof Italic; label: string; command: "italic" }
  | { icon: typeof Strikethrough; label: string; command: "strikeThrough" }
  | {
      icon: typeof Heading1
      label: string
      command: "formatBlock"
      value: "H1"
    }
  | {
      icon: typeof Heading2
      label: string
      command: "formatBlock"
      value: "H2"
    }
  | {
      icon: typeof Heading3
      label: string
      command: "formatBlock"
      value: "H3"
    }
  | { icon: typeof Pilcrow; label: string; command: "formatBlock"; value: "P" }

const richCommands: RichCommand[] = [
  { icon: Bold, label: "Bold", command: "bold" },
  { icon: Italic, label: "Italic", command: "italic" },
  { icon: Strikethrough, label: "Strikethrough", command: "strikeThrough" },
  { icon: Heading1, label: "Heading 1", command: "formatBlock", value: "H1" },
  { icon: Heading2, label: "Heading 2", command: "formatBlock", value: "H2" },
  { icon: Heading3, label: "Heading 3", command: "formatBlock", value: "H3" },
  { icon: Pilcrow, label: "Paragraph", command: "formatBlock", value: "P" },
]

function RichTextField({
  value,
  onChange,
  className,
  "data-testid": testId,
}: {
  value: string
  onChange: (next: string) => void
  className?: string
  "data-testid"?: string
}) {
  const editorRef = useRef<HTMLDivElement | null>(null)
  const [focused, setFocused] = useState(false)

  useEffect(() => {
    const editor = editorRef.current
    if (!editor || window.document.activeElement === editor) return
    editor.innerHTML = markdownToHtml(value)
  }, [value])

  const syncValue = () => {
    const editor = editorRef.current
    if (!editor) return
    onChange(htmlToMarkdown(editor.innerHTML))
  }

  const runCommand = (command: RichCommand) => {
    const editor = editorRef.current
    if (!editor) return
    editor.focus()
    window.document.execCommand(
      command.command,
      false,
      "value" in command ? command.value : undefined,
    )
    syncValue()
  }

  return (
    <div className="space-y-2">
      {focused && (
        <div className="sticky top-[4.25rem] z-10 inline-flex flex-wrap items-center gap-1 rounded-md border bg-background p-1 shadow-sm">
          {richCommands.map((command) => {
            const Icon = command.icon
            return (
              <Button
                key={`${command.command}-${command.label}`}
                type="button"
                variant="ghost"
                size="icon-sm"
                aria-label={command.label}
                title={command.label}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => runCommand(command)}
              >
                <Icon className="size-4" />
              </Button>
            )
          })}
        </div>
      )}
      {/* biome-ignore lint/a11y/useSemanticElements: contenteditable keeps document editing inline instead of form controls */}
      <div
        ref={editorRef}
        role="textbox"
        aria-multiline="true"
        tabIndex={0}
        contentEditable
        suppressContentEditableWarning
        data-testid={testId}
        onFocus={() => setFocused(true)}
        onBlur={() => {
          syncValue()
          setFocused(false)
        }}
        onInput={syncValue}
        className={cn(
          "min-h-10 rounded-sm px-1 py-0.5 text-foreground outline-none transition-colors focus-visible:bg-muted/40 focus-visible:ring-2 focus-visible:ring-sidebar-ring [&_h1]:text-3xl [&_h1]:font-semibold [&_h2]:text-2xl [&_h2]:font-semibold [&_h3]:text-xl [&_h3]:font-semibold [&_p]:my-2",
          className,
        )}
      />
    </div>
  )
}

function PlainInlineEditor({
  value,
  onChange,
  className,
  "data-testid": testId,
}: {
  value: string
  onChange: (next: string) => void
  className?: string
  "data-testid"?: string
}) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!ref.current || window.document.activeElement === ref.current) return
    ref.current.textContent = value
  }, [value])

  const syncValue = () => {
    onChange(ref.current?.textContent ?? "")
  }

  return (
    // biome-ignore lint/a11y/useSemanticElements: contenteditable keeps title and description editing inline
    <div
      ref={ref}
      role="textbox"
      tabIndex={0}
      contentEditable
      suppressContentEditableWarning
      data-testid={testId}
      onInput={syncValue}
      onBlur={syncValue}
      className={cn(
        "rounded-sm px-1 py-0.5 outline-none transition-colors focus-visible:bg-muted/40 focus-visible:ring-2 focus-visible:ring-sidebar-ring",
        className,
      )}
    />
  )
}

function TaskforceDocumentDetail() {
  const { documentId } = Route.useParams()
  const { isDemoMode } = useDemoMode()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const { user } = useAuth()

  const [viewMode, setViewMode] = useState<ViewMode>("summary")
  const [activeEvidenceAnchorId, setActiveEvidenceAnchorId] = useState<string>()
  const [isEditing, setIsEditing] = useState(false)
  const [editState, setEditState] = useState<EditableDoc | null>(null)
  const [anchorMode, setAnchorMode] = useState(false)
  const [summaryPick, setSummaryPick] = useState<AnchorPick | null>(null)
  const [detailsPick, setDetailsPick] = useState<DetailsPick | null>(null)
  const [accessOpen, setAccessOpen] = useState(false)
  const [shareDraft, setShareDraft] = useState<ShareDraft>({})
  const [createFolderOpen, setCreateFolderOpen] = useState(false)
  const handledHashScrollRef = useRef<string | null>(null)

  const documentQuery = useQuery({
    queryKey: ["v2-document", documentId, { demo: isDemoMode }],
    queryFn: () => readV2Document(documentId, { demo: isDemoMode }),
  })

  const document = documentQuery.data
  const isOwner = Boolean(document && user?.id === document.owner_id)
  const canEditDocument = Boolean(document && document.user_access !== "viewer")
  const canManageDocument = isOwner && !isDemoMode

  const foldersQuery = useQuery({
    queryKey: ["v2-document-folders", { demo: isDemoMode }],
    queryFn: () => readV2DocumentFolders({ demo: isDemoMode }),
    enabled: Boolean(document),
  })

  const organizationQuery = useQuery({
    queryKey: ["organization-me"],
    queryFn: readMyOrganization,
    enabled: canManageDocument,
  })

  const sharesQuery = useQuery({
    queryKey: ["v2-document-shares", documentId],
    queryFn: () => readV2DocumentShares(documentId),
    enabled: canManageDocument,
  })

  const updateMutation = useMutation({
    mutationFn: (body: V2DocumentUpdate) =>
      updateV2Document(documentId, body, { demo: document?.is_demo }),
    onSuccess: (data) => {
      queryClient.setQueryData(
        ["v2-document", documentId, { demo: isDemoMode }],
        data,
      )
      queryClient.invalidateQueries({
        queryKey: ["v2-documents", { demo: isDemoMode }],
      })
      queryClient.invalidateQueries({
        queryKey: ["v2-document-folders", { demo: isDemoMode }],
      })
      showSuccessToast("Document saved.")
    },
    onError: () => {
      showErrorToast("Could not save document.")
    },
  })

  const favoriteMutation = useMutation({
    mutationFn: (next: boolean) =>
      next
        ? favoriteV2Document(documentId, { demo: isDemoMode })
        : unfavoriteV2Document(documentId, { demo: isDemoMode }),
    onMutate: async (next) => {
      const documentKey = ["v2-document", documentId, { demo: isDemoMode }]
      await queryClient.cancelQueries({ queryKey: documentKey })
      const previous = queryClient.getQueryData<V2DocumentPublic>(documentKey)
      if (previous) {
        queryClient.setQueryData<V2DocumentPublic>(documentKey, {
          ...previous,
          is_favorite: next,
        })
      }
      return { previous }
    },
    onError: (_error, _next, context) => {
      if (context?.previous) {
        queryClient.setQueryData(
          ["v2-document", documentId, { demo: isDemoMode }],
          context.previous,
        )
      }
      showErrorToast("Could not update favorite.")
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["v2-document", documentId, { demo: isDemoMode }],
      })
      queryClient.invalidateQueries({
        queryKey: ["v2-documents", { demo: isDemoMode }],
      })
    },
  })

  const toggleFavorite = () => {
    if (!document || isDemoMode || favoriteMutation.isPending) return
    favoriteMutation.mutate(!document.is_favorite)
  }

  const shareMutation = useMutation({
    mutationFn: () =>
      replaceV2DocumentShares(documentId, {
        shares: Object.entries(shareDraft).map(([user_id, permission]) => ({
          user_id,
          permission,
        })),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["v2-document", documentId, { demo: isDemoMode }],
      })
      queryClient.invalidateQueries({
        queryKey: ["v2-document-shares", documentId],
      })
      queryClient.invalidateQueries({
        queryKey: ["v2-documents", { demo: isDemoMode }],
      })
      setAccessOpen(false)
      showSuccessToast("Sharing updated.")
    },
    onError: () => {
      showErrorToast("Could not update sharing.")
    },
  })

  const isSplit = viewMode === "split"
  const summaryVisible = viewMode === "summary" || isSplit
  const detailsVisible = viewMode === "details" || isSplit

  const showEvidence = useCallback((anchorId: string) => {
    setActiveEvidenceAnchorId(anchorId)
    setViewMode("split")
    window.setTimeout(() => {
      window.document
        .getElementById(anchorId)
        ?.scrollIntoView({ block: "start", behavior: "smooth" })
    }, 0)
  }, [])

  useEffect(() => {
    if (!document) return

    const rawHash = window.location.hash.slice(1)
    if (!rawHash) return

    let anchorId = rawHash
    try {
      anchorId = decodeURIComponent(rawHash)
    } catch {
      anchorId = rawHash
    }

    const scrollKey = `${document.id}:${anchorId}`
    if (handledHashScrollRef.current === scrollKey) return

    const hasMatchingSection = document.details_markdown_sections.some(
      (section) => section.anchor_id === anchorId,
    )
    if (!hasMatchingSection) return

    handledHashScrollRef.current = scrollKey
    showEvidence(anchorId)
  }, [document, showEvidence])

  const closeSplit = () => {
    setViewMode("summary")
    setActiveEvidenceAnchorId(undefined)
    setAnchorMode(false)
    setSummaryPick(null)
    setDetailsPick(null)
  }

  const enterEdit = () => {
    if (!document || !canEditDocument) return
    setEditState(toEditable(document))
    setIsEditing(true)
    setAnchorMode(false)
    setSummaryPick(null)
    setDetailsPick(null)
  }

  const cancelEdit = () => {
    setIsEditing(false)
    setEditState(null)
  }

  const saveEdit = () => {
    if (!editState) return
    updateMutation.mutate(toUpdatePayload(editState), {
      onSuccess: () => {
        setIsEditing(false)
        setEditState(null)
      },
    })
  }

  const seedShareDraft = () => {
    const shares = sharesQuery.data?.data ?? document?.shared_with ?? []
    setShareDraft(
      Object.fromEntries(
        shares.map((share) => [share.user_id, share.permission]),
      ),
    )
  }

  const setAccessDropdownOpen = (open: boolean) => {
    if (open) seedShareDraft()
    setAccessOpen(open)
  }

  const moveDocumentToFolder = (folderId: string | null) => {
    updateMutation.mutate({ folder_id: folderId })
  }

  const confirmAnchor = () => {
    if (!document || !summaryPick || !detailsPick) return

    const anchorId = shortAnchorId()

    const nextMainBody: V2DocumentParagraph[] = document.main_body.map(
      (paragraph, pIdx) => {
        if (pIdx !== summaryPick.paragraphIndex) return paragraph
        const nextSegments = paragraph.segments.flatMap((segment, sIdx) => {
          if (sIdx !== summaryPick.segmentIndex) return [segment]
          const text = segment.text
          const before = text.slice(0, summaryPick.start)
          const middle = text.slice(summaryPick.start, summaryPick.end)
          const after = text.slice(summaryPick.end)
          const out: V2DocumentParagraph["segments"] = []
          if (before) out.push({ text: before })
          out.push({ text: middle, evidence_anchor_id: anchorId })
          if (after) out.push({ text: after })
          return out
        })
        return { segments: nextSegments }
      },
    )

    const nextDetailsSections: V2DocumentDetailsSection[] =
      document.details_markdown_sections.flatMap((section, idx) => {
        if (idx !== detailsPick.sectionIndex) return [section]
        const md = section.markdown
        const before = md.slice(0, detailsPick.start)
        const middle = md.slice(detailsPick.start, detailsPick.end)
        const after = md.slice(detailsPick.end)
        const out: V2DocumentDetailsSection[] = []
        if (before.trim()) {
          out.push({ anchor_id: `${section.anchor_id}-pre`, markdown: before })
        }
        out.push({ anchor_id: anchorId, markdown: middle })
        if (after.trim()) {
          out.push({ anchor_id: `${section.anchor_id}-post`, markdown: after })
        }
        return out
      })

    updateMutation.mutate(
      {
        main_body: nextMainBody,
        details_markdown_sections: nextDetailsSections,
      },
      {
        onSuccess: () => {
          setAnchorMode(false)
          setSummaryPick(null)
          setDetailsPick(null)
          setActiveEvidenceAnchorId(anchorId)
        },
      },
    )
  }

  if (documentQuery.isLoading) {
    return (
      <section className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto">
        <div className="w-full max-w-3xl text-sm text-muted-foreground">
          Loading document…
        </div>
      </section>
    )
  }

  if (!document) {
    return (
      <section className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto">
        <div className="w-full max-w-3xl">
          <h1 className="text-2xl font-semibold">Document not found</h1>
          <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">
            No document exists for `{documentId}`.
          </p>
          <Button asChild variant="outline" className="mt-6">
            <Link to="/v2/library">Back to library</Link>
          </Button>
        </div>
      </section>
    )
  }

  const editing = isEditing && editState !== null
  const anchorReady = anchorMode && summaryPick && detailsPick

  return (
    <section
      data-testid="v2-document-scroll"
      className={cn(
        "flex min-h-0 flex-1 flex-col",
        isSplit ? "overflow-y-auto md:overflow-hidden" : "overflow-y-auto",
      )}
    >
      <article
        className={cn(
          "mx-auto flex w-full max-w-none flex-col px-4 md:px-6 lg:px-8",
          isSplit ? "md:min-h-0 md:flex-1 md:overflow-hidden" : "pb-16",
        )}
      >
        <div
          data-testid="v2-document-sticky-header"
          className={cn(
            "sticky top-0 z-20 -mx-4 border-b bg-background/95 px-4 pt-3 pb-3 backdrop-blur supports-[backdrop-filter]:bg-background/80 md:-mx-6 md:px-6 lg:-mx-8 lg:px-8",
            isSplit && "md:shrink-0",
          )}
        >
          <div className="-ml-3 mb-3 flex items-center justify-between">
            <Button
              asChild
              variant="ghost"
              size="sm"
              data-testid="v2-document-back-link"
              className="w-fit"
            >
              <Link to="/v2/library">
                <ArrowLeft className="size-4" />
                Library
              </Link>
            </Button>

            <div className="flex items-center gap-2">
              {!canEditDocument && (
                <Badge variant="outline">
                  <Eye className="size-3" />
                  View only
                </Badge>
              )}
              {!editing && canEditDocument && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={enterEdit}
                  data-testid="document-edit"
                >
                  <Pencil className="size-4" />
                  Edit
                </Button>
              )}
              {editing && (
                <>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={cancelEdit}
                    disabled={updateMutation.isPending}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    onClick={saveEdit}
                    disabled={updateMutation.isPending}
                    data-testid="document-save"
                  >
                    {updateMutation.isPending ? "Saving…" : "Save"}
                  </Button>
                </>
              )}
            </div>
          </div>

          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            {editing ? (
              <PlainInlineEditor
                value={editState.title}
                onChange={(next) => setEditState({ ...editState, title: next })}
                className="w-full text-3xl font-semibold tracking-tight text-foreground md:max-w-xl"
                data-testid="edit-title"
              />
            ) : (
              <h1 className="text-3xl font-semibold tracking-tight text-foreground">
                {document.title}
              </h1>
            )}

            <div className="flex flex-wrap items-center gap-2">
              <div
                role="tablist"
                aria-label="Document view"
                className="inline-flex h-9 w-fit shrink-0 items-center justify-center rounded-lg bg-muted p-[3px] text-muted-foreground"
              >
                <ViewToggle
                  label="Summary"
                  active={viewMode === "summary"}
                  onClick={() => {
                    setViewMode("summary")
                    setActiveEvidenceAnchorId(undefined)
                    setAnchorMode(false)
                  }}
                />
                <ViewToggle
                  label="Details"
                  active={viewMode === "details"}
                  onClick={() => {
                    setViewMode("details")
                    setActiveEvidenceAnchorId(undefined)
                    setAnchorMode(false)
                  }}
                />
                <ViewToggle
                  label="Split"
                  active={isSplit}
                  onClick={() => {
                    setViewMode("split")
                    setActiveEvidenceAnchorId(undefined)
                  }}
                />
              </div>

              {isSplit && !editing && canEditDocument && (
                <Button
                  type="button"
                  variant={anchorMode ? "default" : "outline"}
                  size="sm"
                  onClick={() => {
                    if (anchorMode) {
                      setAnchorMode(false)
                      setSummaryPick(null)
                      setDetailsPick(null)
                    } else {
                      setAnchorMode(true)
                    }
                  }}
                  data-testid="anchor-mode-toggle"
                >
                  <LinkIcon className="size-4" />
                  {anchorMode ? "Cancel link" : "Link evidence"}
                </Button>
              )}

              {anchorMode && (
                <Button
                  type="button"
                  size="sm"
                  onClick={confirmAnchor}
                  disabled={!anchorReady || updateMutation.isPending}
                  data-testid="anchor-confirm"
                >
                  {updateMutation.isPending ? "Linking…" : "Confirm anchor"}
                </Button>
              )}
            </div>
          </div>
        </div>

        {editing ? (
          <PlainInlineEditor
            value={editState.ai_generated_summary}
            onChange={(next) =>
              setEditState({ ...editState, ai_generated_summary: next })
            }
            className="mt-5 text-base leading-7 text-muted-foreground"
            data-testid="edit-description"
          />
        ) : (
          <p className="mt-5 text-base leading-7 text-muted-foreground">
            {document.ai_generated_summary || document.description}
          </p>
        )}

        <DocumentMetadata
          document={document}
          folders={foldersQuery.data?.data ?? []}
          canManageLibrary={canManageDocument}
          canFavorite={!isDemoMode}
          organizationMembers={organizationQuery.data?.members ?? []}
          shares={sharesQuery.data?.data ?? document.shared_with ?? []}
          ownerId={document.owner_id}
          accessOpen={accessOpen}
          onAccessOpenChange={setAccessDropdownOpen}
          shareDraft={shareDraft}
          setShareDraft={setShareDraft}
          onSaveAccess={() => shareMutation.mutate()}
          isSavingAccess={shareMutation.isPending}
          isLoadingAccess={sharesQuery.isLoading || organizationQuery.isLoading}
          onMoveFolder={moveDocumentToFolder}
          isMovingFolder={updateMutation.isPending}
          onCreateFolder={() => setCreateFolderOpen(true)}
          onToggleFavorite={toggleFavorite}
          isTogglingFavorite={favoriteMutation.isPending}
          onUpdateDates={(dates) => updateMutation.mutate(dates)}
          isUpdatingDates={updateMutation.isPending}
        />

        <FolderCreateDialog
          open={createFolderOpen}
          onOpenChange={setCreateFolderOpen}
          demo={isDemoMode}
          folders={foldersQuery.data?.data ?? []}
          onCreated={(folder) => moveDocumentToFolder(folder.id)}
        />

        {anchorMode && (
          <AnchorHelper summaryPick={summaryPick} detailsPick={detailsPick} />
        )}

        <div
          className={cn(
            "gap-6",
            isSplit
              ? "mt-8 grid grid-cols-1 md:grid md:min-h-0 md:flex-1 md:grid-cols-2 md:overflow-hidden md:pb-4"
              : "mt-8 block",
          )}
        >
          {summaryVisible && (
            <SummaryPane
              document={document}
              editing={editing}
              editState={editState}
              setEditState={setEditState}
              onShowEvidence={showEvidence}
              isSplit={isSplit}
              anchorMode={anchorMode}
              summaryPick={summaryPick}
              setSummaryPick={setSummaryPick}
            />
          )}

          {detailsVisible && (
            <DetailsPane
              document={document}
              editing={editing}
              editState={editState}
              setEditState={setEditState}
              activeEvidenceAnchorId={activeEvidenceAnchorId}
              showClose={isSplit}
              onClose={closeSplit}
              isSplit={isSplit}
              anchorMode={anchorMode}
              detailsPick={detailsPick}
              setDetailsPick={setDetailsPick}
            />
          )}
        </div>
      </article>
    </section>
  )
}

function DocumentMetadata({
  document,
  folders,
  canManageLibrary,
  canFavorite,
  organizationMembers,
  shares,
  ownerId,
  accessOpen,
  onAccessOpenChange,
  shareDraft,
  setShareDraft,
  onSaveAccess,
  isSavingAccess,
  isLoadingAccess,
  onMoveFolder,
  isMovingFolder,
  onCreateFolder,
  onToggleFavorite,
  isTogglingFavorite,
  onUpdateDates,
  isUpdatingDates,
}: {
  document: V2DocumentPublic
  folders: V2DocumentFolderPublic[]
  canManageLibrary: boolean
  canFavorite: boolean
  organizationMembers: OrganizationMemberPublic[]
  shares: V2DocumentSharePublic[]
  ownerId: string
  accessOpen: boolean
  onAccessOpenChange: (open: boolean) => void
  shareDraft: ShareDraft
  setShareDraft: (next: ShareDraft) => void
  onSaveAccess: () => void
  isSavingAccess: boolean
  isLoadingAccess: boolean
  onMoveFolder: (folderId: string | null) => void
  isMovingFolder: boolean
  onCreateFolder: () => void
  onToggleFavorite: () => void
  isTogglingFavorite: boolean
  onUpdateDates: (dates: { created_at?: string; updated_at?: string }) => void
  isUpdatingDates: boolean
}) {
  const sharedCount = shares.length

  return (
    <div className="mt-5 flex flex-wrap items-center gap-2 border-y py-3 text-sm text-muted-foreground">
      <DocumentDateField
        label="Created"
        value={document.created_at}
        canEdit={canManageLibrary}
        disabled={isUpdatingDates}
        onChange={(iso) => onUpdateDates({ created_at: iso })}
      />
      <DocumentDateField
        label="Updated"
        value={document.updated_at}
        canEdit={canManageLibrary}
        disabled={isUpdatingDates}
        onChange={(iso) => onUpdateDates({ updated_at: iso })}
      />

      {canManageLibrary ? (
        <FolderPickerDropdown
          folders={folders}
          currentFolderId={document.folder_id ?? null}
          disabled={isMovingFolder}
          onSelect={onMoveFolder}
          onCreateFolder={onCreateFolder}
          triggerLabel={document.folder_name ?? "Unfiled"}
        />
      ) : (
        <span className="inline-flex min-w-0 items-center gap-1.5 text-foreground">
          <Folder className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{document.folder_name ?? "Unfiled"}</span>
        </span>
      )}

      {canManageLibrary ? (
        <DocumentAccessDropdown
          open={accessOpen}
          onOpenChange={onAccessOpenChange}
          members={organizationMembers}
          ownerId={ownerId}
          shares={shares}
          shareDraft={shareDraft}
          setShareDraft={setShareDraft}
          onSave={onSaveAccess}
          isSaving={isSavingAccess}
          isLoading={isLoadingAccess}
        />
      ) : (
        <span className="inline-flex items-center gap-1.5 text-foreground">
          <Share2 className="size-4 text-muted-foreground" />
          {sharedCount > 0
            ? `${sharedCount} member${sharedCount === 1 ? "" : "s"}`
            : "Private"}
        </span>
      )}

      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={!canFavorite || isTogglingFavorite}
        aria-label={document.is_favorite ? "Remove favorite" : "Add favorite"}
        aria-pressed={document.is_favorite}
        onClick={onToggleFavorite}
        data-testid="document-favorite"
      >
        <Star
          className={cn(
            "size-4",
            document.is_favorite
              ? "fill-yellow-400 text-yellow-500"
              : "text-muted-foreground",
          )}
        />
        {document.is_favorite ? "Favorited" : "Favorite"}
      </Button>
    </div>
  )
}

function DocumentDateField({
  label,
  value,
  canEdit,
  disabled,
  onChange,
}: {
  label: string
  value: string | null
  canEdit: boolean
  disabled: boolean
  onChange: (iso: string) => void
}) {
  const [editing, setEditing] = useState(false)
  const inputValue = value ? value.slice(0, 10) : ""
  const display = `${label} ${formatDateOnly(value)}`

  if (!canEdit) {
    return (
      <span className="whitespace-nowrap text-xs text-muted-foreground">
        {display}
      </span>
    )
  }

  if (editing) {
    return (
      <input
        type="date"
        // biome-ignore lint/a11y/noAutofocus: opened by an explicit click, focus belongs here
        autoFocus
        defaultValue={inputValue}
        disabled={disabled}
        aria-label={`${label} date`}
        className="rounded border border-input bg-background px-1.5 py-0.5 text-xs text-foreground"
        onBlur={() => setEditing(false)}
        onChange={(event) => {
          const next = event.target.value
          if (next && next !== inputValue) {
            const iso = new Date(`${next}T00:00:00Z`).toISOString()
            onChange(iso)
          }
          setEditing(false)
        }}
      />
    )
  }

  return (
    <button
      type="button"
      className="cursor-pointer whitespace-nowrap rounded px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground"
      onClick={() => setEditing(true)}
      disabled={disabled}
    >
      {display}
    </button>
  )
}

function DocumentAccessDropdown({
  open,
  onOpenChange,
  members,
  ownerId,
  shares,
  shareDraft,
  setShareDraft,
  onSave,
  isSaving,
  isLoading,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  members: OrganizationMemberPublic[]
  ownerId: string
  shares: V2DocumentSharePublic[]
  shareDraft: ShareDraft
  setShareDraft: (draft: ShareDraft) => void
  onSave: () => void
  isSaving: boolean
  isLoading: boolean
}) {
  const [query, setQuery] = useState("")
  const shareableMembers = members.filter((member) => member.id !== ownerId)
  const filteredMembers = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return shareableMembers
    return shareableMembers.filter((member) =>
      [member.full_name, member.email]
        .filter(Boolean)
        .some((value) => value?.toLowerCase().includes(needle)),
    )
  }, [query, shareableMembers])
  const assignedCount = Object.keys(shareDraft).length
  const persistedCount = shares.length

  return (
    <DropdownMenu
      open={open}
      onOpenChange={(nextOpen) => {
        onOpenChange(nextOpen)
        if (!nextOpen) setQuery("")
      }}
    >
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-testid="document-access"
        >
          <Share2 className="size-4" />
          {persistedCount > 0
            ? `${persistedCount} member${persistedCount === 1 ? "" : "s"}`
            : "Private"}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-[360px] p-2">
        <div className="relative mb-2">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => event.stopPropagation()}
            placeholder="Search organization users"
            className="h-8 pl-8"
          />
        </div>
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {isLoading && (
            <div className="px-2 py-3 text-sm text-muted-foreground">
              Loading access…
            </div>
          )}
          {!isLoading && shareableMembers.length === 0 && (
            <div className="px-2 py-3 text-sm text-muted-foreground">
              No organization members available.
            </div>
          )}
          {!isLoading &&
            filteredMembers.length === 0 &&
            shareableMembers.length > 0 && (
              <div className="px-2 py-3 text-sm text-muted-foreground">
                No users found.
              </div>
            )}
          {!isLoading &&
            filteredMembers.map((member) => {
              const permission = shareDraft[member.id]
              const checked = Boolean(permission)
              return (
                <div
                  key={member.id}
                  className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 rounded-md border p-2"
                >
                  <Checkbox
                    id={`share-${member.id}`}
                    checked={checked}
                    onCheckedChange={(nextChecked) => {
                      const next = { ...shareDraft }
                      if (nextChecked === true) {
                        next[member.id] = permission ?? "editor"
                      } else {
                        delete next[member.id]
                      }
                      setShareDraft(next)
                    }}
                  />
                  <label htmlFor={`share-${member.id}`} className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground">
                      {member.full_name || member.email}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">
                      {member.email}
                    </span>
                  </label>
                  <div className="flex rounded-md border p-0.5">
                    {(["viewer", "editor"] as V2DocumentSharePermission[]).map(
                      (option) => (
                        <button
                          key={option}
                          type="button"
                          disabled={!checked}
                          onClick={() =>
                            setShareDraft({
                              ...shareDraft,
                              [member.id]: option,
                            })
                          }
                          className={cn(
                            "rounded px-2 py-1 text-xs capitalize disabled:opacity-40",
                            permission === option &&
                              "bg-foreground text-background",
                          )}
                        >
                          {option}
                        </button>
                      ),
                    )}
                  </div>
                </div>
              )
            })}
        </div>
        <div className="mt-2 flex items-center justify-between border-t pt-2">
          <span className="text-xs text-muted-foreground">
            {assignedCount} selected
          </span>
          <Button type="button" size="sm" onClick={onSave} disabled={isSaving}>
            {isSaving ? "Saving" : "Save access"}
          </Button>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

function ViewToggle({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      data-state={active ? "active" : "inactive"}
      onClick={onClick}
      className="inline-flex h-[calc(100%-1px)] flex-1 items-center justify-center gap-1.5 whitespace-nowrap rounded-md border border-transparent px-3 py-1 text-sm font-medium text-foreground transition-[color,box-shadow] focus-visible:border-ring focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=active]:bg-background data-[state=active]:shadow-sm dark:text-muted-foreground dark:data-[state=active]:border-input dark:data-[state=active]:bg-input/30 dark:data-[state=active]:text-foreground"
    >
      {label}
    </button>
  )
}

function AnchorHelper({
  summaryPick,
  detailsPick,
}: {
  summaryPick: AnchorPick | null
  detailsPick: DetailsPick | null
}) {
  return (
    <div
      className="mt-3 rounded-md border border-dashed border-purple-300 bg-purple-50/60 px-3 py-2 text-xs text-purple-900 dark:border-purple-900 dark:bg-purple-950/30 dark:text-purple-100"
      data-testid="anchor-helper"
    >
      <p className="font-medium">Linking evidence</p>
      <ol className="mt-1 list-decimal space-y-0.5 pl-5">
        <li>
          {summaryPick ? (
            <>
              Summary selected: <em>"{summaryPick.text}"</em>
            </>
          ) : (
            "Select text in Summary (within a non-anchored span)."
          )}
        </li>
        <li>
          {detailsPick ? (
            <>
              Details selected: <em>"{detailsPick.text.slice(0, 60)}…"</em>
            </>
          ) : (
            "Select text in Details (within a single section)."
          )}
        </li>
        <li>Confirm to create the anchor.</li>
      </ol>
    </div>
  )
}

function SummaryPane({
  document,
  editing,
  editState,
  setEditState,
  onShowEvidence,
  isSplit,
  anchorMode,
  summaryPick,
  setSummaryPick,
}: {
  document: V2DocumentPublic
  editing: boolean
  editState: EditableDoc | null
  setEditState: (next: EditableDoc) => void
  onShowEvidence: (anchorId: string) => void
  isSplit: boolean
  anchorMode: boolean
  summaryPick: AnchorPick | null
  setSummaryPick: (pick: AnchorPick | null) => void
}) {
  const reportRef = useRef<HTMLDivElement | null>(null)

  const handleSummarySelection = () => {
    if (!anchorMode || !reportRef.current) return
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return
    }
    const range = selection.getRangeAt(0)
    const startSpan = (range.startContainer.parentElement?.closest(
      "[data-segment-key]",
    ) ?? null) as HTMLElement | null
    const endSpan = (range.endContainer.parentElement?.closest(
      "[data-segment-key]",
    ) ?? null) as HTMLElement | null
    if (!startSpan || !endSpan || startSpan !== endSpan) return
    if (startSpan.dataset.anchored === "true") return

    const key = startSpan.dataset.segmentKey
    if (!key) return
    const [pIdxStr, sIdxStr] = key.split("-")
    const paragraphIndex = Number(pIdxStr)
    const segmentIndex = Number(sIdxStr)

    const start = getOffsetWithin(
      startSpan,
      range.startContainer,
      range.startOffset,
    )
    const end = getOffsetWithin(startSpan, range.endContainer, range.endOffset)
    if (start < 0 || end < 0 || end <= start) return

    const text = startSpan.textContent?.slice(start, end) ?? ""
    if (!text) return

    setSummaryPick({ paragraphIndex, segmentIndex, start, end, text })
  }

  return (
    <div
      className={cn(
        "space-y-9",
        isSplit && "md:min-h-0 md:overflow-y-auto md:pb-4 md:pr-2",
      )}
    >
      <section className="space-y-3">
        {editing && editState ? (
          <EditableMainBody
            paragraphs={editState.main_body}
            onChange={(next) => setEditState({ ...editState, main_body: next })}
          />
        ) : (
          // biome-ignore lint/a11y/noStaticElementInteractions: captures text selection for evidence anchoring
          <div
            ref={reportRef}
            onMouseUp={handleSummarySelection}
            onKeyUp={handleSummarySelection}
            className={cn(
              "space-y-5 text-base leading-8 text-foreground",
              anchorMode && "cursor-text select-text",
            )}
          >
            {document.main_body.map((paragraph, paragraphIndex) => {
              const hasAnchors = paragraph.segments.some(
                (segment) => segment.evidence_anchor_id,
              )
              if (!hasAnchors && paragraph.segments.length === 1) {
                return (
                  <MarkdownBlocks
                    key={paragraphIndex}
                    markdown={paragraph.segments[0].text}
                  />
                )
              }

              return (
                <p key={paragraphIndex}>
                  {paragraph.segments.map((segment, segmentIndex) => {
                    const segmentKey = `${paragraphIndex}-${segmentIndex}`
                    const isAnchored = Boolean(segment.evidence_anchor_id)
                    const isPicked =
                      summaryPick?.paragraphIndex === paragraphIndex &&
                      summaryPick?.segmentIndex === segmentIndex

                    if (!isAnchored) {
                      return (
                        <span
                          key={segmentKey}
                          data-segment-key={segmentKey}
                          data-anchored="false"
                          className={cn(
                            isPicked && "bg-purple-100 dark:bg-purple-950/60",
                          )}
                        >
                          {renderInlineMarkdown(
                            segment.text,
                            `segment-${segmentKey}`,
                          )}
                        </span>
                      )
                    }

                    const evidenceAnchorId =
                      segment.evidence_anchor_id as string
                    return (
                      <button
                        key={segmentKey}
                        type="button"
                        data-segment-key={segmentKey}
                        data-anchored="true"
                        aria-label={`Show evidence for: ${segment.text}`}
                        data-testid={`human-evidence-${evidenceAnchorId}`}
                        onClick={() => {
                          if (anchorMode) return
                          onShowEvidence(evidenceAnchorId)
                        }}
                        className="inline rounded-sm bg-purple-100/80 px-1 py-0.5 text-left text-purple-950 transition-colors hover:bg-purple-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-purple-400 dark:bg-purple-950/50 dark:text-purple-100 dark:hover:bg-purple-900/70"
                      >
                        {renderInlineMarkdown(
                          segment.text,
                          `segment-${segmentKey}`,
                        )}
                      </button>
                    )
                  })}
                </p>
              )
            })}
          </div>
        )}
      </section>
    </div>
  )
}

function paragraphsToMarkdown(paragraphs: V2DocumentParagraph[]): string {
  return paragraphs
    .map((paragraph) => paragraph.segments.map((s) => s.text).join(""))
    .join("\n\n")
}

function markdownToParagraphs(markdown: string): V2DocumentParagraph[] {
  return [{ segments: [{ text: markdown }] }]
}

function EditableMainBody({
  paragraphs,
  onChange,
}: {
  paragraphs: V2DocumentParagraph[]
  onChange: (next: V2DocumentParagraph[]) => void
}) {
  const markdown = useMemo(() => paragraphsToMarkdown(paragraphs), [paragraphs])

  return (
    <RichTextField
      value={markdown}
      onChange={(next) => onChange(markdownToParagraphs(next))}
      className="text-base leading-8"
      data-testid="edit-main-body"
    />
  )
}

function DetailsPane({
  document,
  editing,
  editState,
  setEditState,
  activeEvidenceAnchorId,
  showClose,
  onClose,
  isSplit,
  anchorMode,
  detailsPick,
  setDetailsPick,
}: {
  document: V2DocumentPublic
  editing: boolean
  editState: EditableDoc | null
  setEditState: (next: EditableDoc) => void
  activeEvidenceAnchorId: string | undefined
  showClose: boolean
  onClose: () => void
  isSplit: boolean
  anchorMode: boolean
  detailsPick: DetailsPick | null
  setDetailsPick: (pick: DetailsPick | null) => void
}) {
  const containerRef = useRef<HTMLDivElement | null>(null)

  const sections = useMemo(
    () =>
      editing && editState
        ? editState.details_markdown_sections
        : document.details_markdown_sections,
    [editing, editState, document],
  )

  const fileName =
    editing && editState
      ? editState.details_file_name
      : document.details_file_name

  const handleDetailsSelection = () => {
    if (!anchorMode || !containerRef.current) return
    const selection = window.getSelection()
    if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
      return
    }
    const range = selection.getRangeAt(0)
    const startBlock = (range.startContainer.parentElement?.closest(
      "[data-section-key]",
    ) ?? null) as HTMLElement | null
    const endBlock = (range.endContainer.parentElement?.closest(
      "[data-section-key]",
    ) ?? null) as HTMLElement | null
    if (!startBlock || !endBlock || startBlock !== endBlock) return

    const key = startBlock.dataset.sectionKey
    if (!key) return
    const sectionIndex = Number(key)

    const start = getOffsetWithin(
      startBlock,
      range.startContainer,
      range.startOffset,
    )
    const end = getOffsetWithin(startBlock, range.endContainer, range.endOffset)
    if (start < 0 || end < 0 || end <= start) return
    const text = startBlock.textContent?.slice(start, end) ?? ""
    if (!text) return

    setDetailsPick({ sectionIndex, start, end, text })
  }

  return (
    <section
      aria-label={`${fileName} markdown details`}
      className={cn(
        "overflow-hidden rounded-md border bg-card",
        isSplit && "md:flex md:min-h-0 md:flex-col",
      )}
    >
      <div
        className={cn(
          "flex items-center justify-between gap-3 border-b bg-muted/40 px-4 py-2 font-mono text-xs text-muted-foreground",
          isSplit && "md:shrink-0",
        )}
      >
        {editing && editState ? (
          <input
            type="text"
            value={editState.details_file_name}
            onChange={(event) =>
              setEditState({
                ...editState,
                details_file_name: event.target.value,
              })
            }
            className="min-w-0 flex-1 truncate border bg-background px-2 py-1 font-mono text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
            data-testid="edit-details-filename"
          />
        ) : (
          <span className="truncate">{fileName}</span>
        )}
        {showClose && (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="evidence-split-close"
            aria-label="Close details pane"
            onClick={onClose}
            className="-mr-2 h-7 px-2 text-muted-foreground hover:text-foreground"
          >
            <X className="size-4" />
            <span className="font-sans">Close</span>
          </Button>
        )}
      </div>
      {/* biome-ignore lint/a11y/noStaticElementInteractions: captures text selection for evidence anchoring */}
      <div
        ref={containerRef}
        onMouseUp={handleDetailsSelection}
        onKeyUp={handleDetailsSelection}
        className={cn(
          "px-5 py-4",
          isSplit && "md:min-h-0 md:flex-1 md:overflow-y-auto",
          anchorMode && "cursor-text select-text",
        )}
      >
        {sections.map((section, sectionIndex) => {
          const isActive = activeEvidenceAnchorId === section.anchor_id
          const isPicked = detailsPick?.sectionIndex === sectionIndex

          if (editing && editState) {
            return (
              <RichTextField
                key={`${section.anchor_id}-${sectionIndex}`}
                value={section.markdown}
                onChange={(nextMarkdown) => {
                  const next = editState.details_markdown_sections.map(
                    (s, idx) =>
                      idx === sectionIndex
                        ? { ...s, markdown: nextMarkdown }
                        : s,
                  )
                  setEditState({
                    ...editState,
                    details_markdown_sections: next,
                  })
                }}
                className="mb-5 text-sm leading-7"
                data-testid={`edit-section-${section.anchor_id}`}
              />
            )
          }

          return (
            <div
              key={`${section.anchor_id}-${sectionIndex}`}
              id={section.anchor_id}
              data-section-key={sectionIndex}
              data-testid={`ai-evidence-${section.anchor_id}`}
              data-active-evidence={isActive ? "true" : "false"}
              className={cn(
                "scroll-mt-6 rounded-sm py-2 text-sm leading-7 text-foreground transition-colors",
                isActive &&
                  "bg-purple-100/80 px-3 text-purple-950 dark:bg-purple-950/60 dark:text-purple-100",
                isPicked && "outline outline-2 outline-purple-400",
              )}
            >
              <MarkdownBlocks markdown={section.markdown} />
            </div>
          )
        })}
      </div>
    </section>
  )
}
