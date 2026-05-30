import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  createFileRoute,
  Link,
  Outlet,
  useNavigate,
  useRouterState,
} from "@tanstack/react-router"
import {
  Building2,
  CalendarDays,
  ChevronDown,
  ChevronRight,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  MoreHorizontal,
  Pencil,
  Plus,
  Share2,
  Star,
  Trash2,
  Users,
} from "lucide-react"
import {
  createContext,
  type DragEvent,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import {
  createV2Document,
  deleteV2Document,
  favoriteV2Document,
  readV2DocumentFolders,
  readV2Documents,
  unfavoriteV2Document,
  updateV2Document,
  updateV2DocumentFolder,
  type V2DocumentFolderPublic,
  type V2DocumentFoldersPublic,
  type V2DocumentPublic,
  type V2DocumentsPublic,
  type V2DocumentVisibility,
} from "@/api/v2Documents"
import { useDemoMode } from "@/components/demo-mode-provider"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Skeleton } from "@/components/ui/skeleton"
import {
  FolderActionsMenu,
  FolderCreateDialog,
  FolderPickerDropdown,
} from "@/components/V2/Library/FolderControls"
import useCustomToast from "@/hooks/useCustomToast"
import {
  enumDeserializer,
  persistedKey,
  usePersistentState,
} from "@/hooks/usePersistentState"
import { cn } from "@/lib/utils"

export const Route = createFileRoute("/v2/library")({
  component: TaskforceLibrary,
  head: () => ({
    meta: [
      {
        title: "Taskforce | Library",
      },
    ],
  }),
})

function formatDateOnly(value: string | null): string {
  if (!value) return "—"
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value))
}

type FolderTreeNode = {
  folder: V2DocumentFolderPublic
  children: FolderTreeNode[]
}

type DirectoryDropTargetId = "root" | "unfiled" | string
type OwnershipFilter = "owned" | "shared"
type FavoriteUpdate = { documentId: string; favorite: boolean }

function buildFolderTree(folders: V2DocumentFolderPublic[]): FolderTreeNode[] {
  const nodes = new Map<string, FolderTreeNode>()
  for (const folder of folders) {
    nodes.set(folder.id, { folder, children: [] })
  }

  const roots: FolderTreeNode[] = []
  for (const node of nodes.values()) {
    const parentId = node.folder.parent_folder_id
    const parent =
      parentId && parentId !== node.folder.id ? nodes.get(parentId) : null
    if (parent) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  }

  return roots
}

function isDescendantFolder(
  folders: V2DocumentFolderPublic[],
  parentFolderId: string | null,
  folderId: string,
) {
  if (!parentFolderId) return false
  const byId = new Map(folders.map((folder) => [folder.id, folder]))
  let current = byId.get(parentFolderId)
  const seen = new Set<string>()
  while (current) {
    if (current.id === folderId) return true
    if (!current.parent_folder_id || seen.has(current.id)) return false
    seen.add(current.id)
    current = byId.get(current.parent_folder_id)
  }
  return false
}

const FILES_PAGE_SIZE = 24

type DocumentDeleteHandlers = {
  canDelete: boolean
  onDelete: (document: V2DocumentPublic) => void
}

const DocumentDeleteContext = createContext<DocumentDeleteHandlers | null>(null)

function useDocumentDelete(): DocumentDeleteHandlers {
  return (
    useContext(DocumentDeleteContext) ?? {
      canDelete: false,
      onDelete: () => {},
    }
  )
}

function TaskforceLibrary() {
  const { currentUser } = Route.useRouteContext()
  const { isDemoMode } = useDemoMode()
  const router = useRouterState()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [libraryView, setLibraryView] = usePersistentState<"files" | "folders">(
    "library.view",
    "files",
    { deserialize: enumDeserializer(["files", "folders"]) },
  )
  const [ownershipFilter, setOwnershipFilter] =
    usePersistentState<OwnershipFilter>("library.ownership", "owned", {
      deserialize: enumDeserializer(["owned", "shared"]),
    })
  const [selectedFolderId, setSelectedFolderId] = useState("all")
  const [createFolderOpen, setCreateFolderOpen] = useState(false)
  const [createDocumentOpen, setCreateDocumentOpen] = useState(false)
  const [deleteDocumentTarget, setDeleteDocumentTarget] =
    useState<V2DocumentPublic | null>(null)
  // openFolderIds is the source of truth for which folders are expanded in the
  // Folder Directory view. We persist the array form because Sets don't survive
  // JSON.stringify; the Set view is derived for downstream callers that use
  // `.has()` / `.add()`.
  const [persistedOpenFolders, setPersistedOpenFolders] = usePersistentState<
    string[]
  >(
    persistedKey(
      "library.openFolders",
      currentUser.id,
      isDemoMode ? "demo" : "live",
    ),
    () => ["favorites", "unfiled"],
    {
      deserialize: (raw) =>
        Array.isArray(raw)
          ? raw.filter((v): v is string => typeof v === "string")
          : undefined,
    },
  )
  const openFolderIds = useMemo(
    () => new Set(persistedOpenFolders),
    [persistedOpenFolders],
  )
  const setOpenFolderIds = useCallback(
    (next: Set<string> | ((current: Set<string>) => Set<string>)) => {
      setPersistedOpenFolders((prev) => {
        const prevSet = new Set(prev)
        const nextSet = typeof next === "function" ? next(prevSet) : next
        return Array.from(nextSet)
      })
    },
    [setPersistedOpenFolders],
  )
  const [dragOverFolderId, setDragOverFolderId] =
    useState<DirectoryDropTargetId | null>(null)
  const documentsQueryKey = ["v2-documents", { demo: isDemoMode }] as const
  const foldersQueryKey = ["v2-document-folders", { demo: isDemoMode }] as const

  const documentsQuery = useQuery({
    queryKey: documentsQueryKey,
    queryFn: () => readV2Documents({ demo: isDemoMode }),
  })

  const foldersQuery = useQuery({
    queryKey: foldersQueryKey,
    queryFn: () => readV2DocumentFolders({ demo: isDemoMode }),
  })

  const moveDocumentMutation = useMutation({
    mutationFn: ({
      documentId,
      folderId,
    }: {
      documentId: string
      folderId: string | null
    }) =>
      updateV2Document(
        documentId,
        { folder_id: folderId },
        { demo: isDemoMode },
      ),
    onMutate: async ({ documentId, folderId }) => {
      await queryClient.cancelQueries({ queryKey: documentsQueryKey })
      const previousDocuments =
        queryClient.getQueryData<V2DocumentsPublic>(documentsQueryKey)
      const targetFolder = folderId
        ? folders.find((folder) => folder.id === folderId)
        : null

      queryClient.setQueryData<V2DocumentsPublic>(
        documentsQueryKey,
        (current) => {
          if (!current) return current
          return {
            ...current,
            data: current.data.map((document) =>
              document.id === documentId
                ? {
                    ...document,
                    folder_id: folderId,
                    folder_name: targetFolder?.name ?? null,
                  }
                : document,
            ),
          }
        },
      )

      return { previousDocuments }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: documentsQueryKey,
      })
      showSuccessToast("Document moved.")
    },
    onError: (_error, _variables, context) => {
      if (context?.previousDocuments) {
        queryClient.setQueryData(documentsQueryKey, context.previousDocuments)
      }
      showErrorToast("Could not move document.")
    },
    onSettled: () => {
      setDragOverFolderId(null)
    },
  })

  const moveFolderMutation = useMutation({
    mutationFn: ({
      folderId,
      parentFolderId,
    }: {
      folderId: string
      parentFolderId: string | null
    }) =>
      updateV2DocumentFolder(folderId, { parent_folder_id: parentFolderId }),
    onMutate: async ({ folderId, parentFolderId }) => {
      await queryClient.cancelQueries({ queryKey: foldersQueryKey })
      const previousFolders =
        queryClient.getQueryData<V2DocumentFoldersPublic>(foldersQueryKey)

      queryClient.setQueryData<V2DocumentFoldersPublic>(
        foldersQueryKey,
        (current) => {
          if (!current) return current
          return {
            ...current,
            data: current.data.map((folder) =>
              folder.id === folderId
                ? { ...folder, parent_folder_id: parentFolderId }
                : folder,
            ),
          }
        },
      )

      return { previousFolders }
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: foldersQueryKey })
      showSuccessToast("Folder moved.")
    },
    onError: (_error, _variables, context) => {
      if (context?.previousFolders) {
        queryClient.setQueryData(foldersQueryKey, context.previousFolders)
      }
      showErrorToast("Could not move folder.")
    },
    onSettled: () => {
      setDragOverFolderId(null)
    },
  })

  const favoriteMutation = useMutation({
    mutationFn: ({ documentId, favorite }: FavoriteUpdate) =>
      favorite
        ? favoriteV2Document(documentId, { demo: isDemoMode })
        : unfavoriteV2Document(documentId, { demo: isDemoMode }),
    onMutate: async ({ documentId, favorite }) => {
      await queryClient.cancelQueries({ queryKey: documentsQueryKey })
      const previousDocuments =
        queryClient.getQueryData<V2DocumentsPublic>(documentsQueryKey)

      queryClient.setQueryData<V2DocumentsPublic>(
        documentsQueryKey,
        (current) => {
          if (!current) return current
          return {
            ...current,
            data: current.data.map((document) =>
              document.id === documentId
                ? { ...document, is_favorite: favorite }
                : document,
            ),
          }
        },
      )

      return { previousDocuments }
    },
    onError: (_error, _variables, context) => {
      if (context?.previousDocuments) {
        queryClient.setQueryData(documentsQueryKey, context.previousDocuments)
      }
      showErrorToast("Could not update favorite.")
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: documentsQueryKey })
    },
  })

  const createDocumentMutation = useMutation({
    mutationFn: ({
      title,
      folderId,
    }: {
      title: string
      folderId: string | null
    }) =>
      createV2Document(
        {
          title,
          folder_id: folderId,
        },
        { demo: isDemoMode },
      ),
    onSuccess: (document) => {
      queryClient.invalidateQueries({ queryKey: documentsQueryKey })
      queryClient.invalidateQueries({ queryKey: foldersQueryKey })
      setCreateDocumentOpen(false)
      showSuccessToast("Document created.")
      navigate({
        to: "/v2/library/$documentId",
        params: { documentId: document.id },
      })
    },
    onError: () => {
      showErrorToast("Could not create document.")
    },
  })

  const deleteDocumentMutation = useMutation({
    mutationFn: (documentId: string) =>
      deleteV2Document(documentId, { demo: isDemoMode }),
    onMutate: async (documentId) => {
      await queryClient.cancelQueries({ queryKey: documentsQueryKey })
      const previousDocuments =
        queryClient.getQueryData<V2DocumentsPublic>(documentsQueryKey)
      queryClient.setQueryData<V2DocumentsPublic>(
        documentsQueryKey,
        (current) => {
          if (!current) return current
          return {
            ...current,
            data: current.data.filter((document) => document.id !== documentId),
            count: Math.max(0, current.count - 1),
          }
        },
      )
      return { previousDocuments }
    },
    onError: (_error, _variables, context) => {
      if (context?.previousDocuments) {
        queryClient.setQueryData(documentsQueryKey, context.previousDocuments)
      }
      showErrorToast("Could not delete document.")
    },
    onSuccess: () => {
      showSuccessToast("Document deleted.")
    },
    onSettled: () => {
      setDeleteDocumentTarget(null)
      queryClient.invalidateQueries({ queryKey: documentsQueryKey })
    },
  })

  const allDocuments = documentsQuery.data?.data ?? []
  const documents = useMemo(() => {
    if (ownershipFilter === "owned") {
      return allDocuments.filter(
        (document) => document.owner_id === currentUser.id,
      )
    }
    return allDocuments.filter(
      (document) => document.owner_id !== currentUser.id,
    )
  }, [allDocuments, currentUser.id, ownershipFilter])
  const folders = foldersQuery.data?.data ?? []
  const folderTree = useMemo(() => buildFolderTree(folders), [folders])
  const favoriteDocuments = useMemo(
    () => documents.filter((document) => document.is_favorite),
    [documents],
  )
  const folderCounts = useMemo(() => {
    const counts = new Map<string, number>()
    let unfiled = 0
    for (const document of documents) {
      if (document.folder_id) {
        counts.set(
          document.folder_id,
          (counts.get(document.folder_id) ?? 0) + 1,
        )
      } else {
        unfiled += 1
      }
    }
    return { counts, unfiled }
  }, [documents])
  const visibleDocuments = useMemo(() => {
    if (selectedFolderId === "all") return documents
    if (selectedFolderId === "favorites") return favoriteDocuments
    if (selectedFolderId === "unfiled") {
      return documents.filter((document) => !document.folder_id)
    }
    return documents.filter(
      (document) => document.folder_id === selectedFolderId,
    )
  }, [documents, favoriteDocuments, selectedFolderId])
  const documentsByFolder = useMemo(() => {
    const grouped = new Map<string, V2DocumentPublic[]>()
    grouped.set("favorites", [])
    grouped.set("unfiled", [])
    for (const folder of folders) {
      grouped.set(folder.id, [])
    }
    for (const document of documents) {
      const folderId =
        document.folder_id && grouped.has(document.folder_id)
          ? document.folder_id
          : "unfiled"
      grouped.get(folderId)?.push(document)
      if (document.is_favorite) {
        grouped.get("favorites")?.push(document)
      }
    }
    return grouped
  }, [documents, folders])
  const isLoading = documentsQuery.isLoading || foldersQuery.isLoading
  const isEmpty =
    !isLoading &&
    documents.length === 0 &&
    (libraryView === "files" || folders.length === 0)
  const isFolderEmpty =
    !isLoading && documents.length > 0 && visibleDocuments.length === 0
  const canMutateLibrary =
    !isDemoMode &&
    !moveDocumentMutation.isPending &&
    !moveFolderMutation.isPending &&
    !favoriteMutation.isPending

  // Only hand off to a child route when the URL actually has a document
  // segment after /v2/library/. A bare /v2/library/ (trailing slash, no id)
  // still belongs to this component — otherwise the empty Outlet would render
  // as a blank screen after a hard refresh.
  const pathname = router.location.pathname
  if (
    pathname.startsWith("/v2/library/") &&
    pathname.replace(/\/+$/, "") !== "/v2/library"
  ) {
    return <Outlet />
  }

  const toggleFolderOpen = (folderId: string) => {
    setOpenFolderIds((current) => {
      const next = new Set(current)
      if (next.has(folderId)) {
        next.delete(folderId)
      } else {
        next.add(folderId)
      }
      return next
    })
  }

  const moveDocument = (documentId: string, folderId: string | null) => {
    if (
      isDemoMode ||
      moveDocumentMutation.isPending ||
      moveFolderMutation.isPending
    )
      return
    const document = allDocuments.find((item) => item.id === documentId)
    if (!document || (document.folder_id ?? null) === folderId) {
      setDragOverFolderId(null)
      return
    }
    moveDocumentMutation.mutate({ documentId, folderId })
  }

  const moveFolder = (folderId: string, parentFolderId: string | null) => {
    if (
      isDemoMode ||
      moveDocumentMutation.isPending ||
      moveFolderMutation.isPending
    )
      return
    const folder = folders.find((item) => item.id === folderId)
    if (
      !folder ||
      folder.id === parentFolderId ||
      (folder.parent_folder_id ?? null) === parentFolderId ||
      isDescendantFolder(folders, parentFolderId, folder.id)
    ) {
      setDragOverFolderId(null)
      return
    }
    moveFolderMutation.mutate({ folderId, parentFolderId })
  }

  const handleFolderDragOver = (
    event: DragEvent<HTMLElement>,
    folderId: DirectoryDropTargetId,
  ) => {
    if (isDemoMode) return
    event.preventDefault()
    event.dataTransfer.dropEffect = "move"
    setDragOverFolderId(folderId)
  }

  const handleFolderDrop = (
    event: DragEvent<HTMLElement>,
    folderId: string | null,
  ) => {
    event.preventDefault()
    const folderDropId = event.dataTransfer.getData("application/x-v2-folder")
    if (folderDropId) {
      if (folderId) {
        setOpenFolderIds((current) => new Set(current).add(folderId))
      }
      moveFolder(folderDropId, folderId)
      return
    }

    const documentId = event.dataTransfer.getData("application/x-v2-document")
    if (!documentId) return
    if (folderId) {
      setOpenFolderIds((current) => new Set(current).add(folderId))
    }
    moveDocument(documentId, folderId)
  }

  const handleUnfiledDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    const documentId = event.dataTransfer.getData("application/x-v2-document")
    if (documentId) {
      moveDocument(documentId, null)
    }
  }

  const handleRootFolderDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault()
    const folderId = event.dataTransfer.getData("application/x-v2-folder")
    if (folderId) {
      moveFolder(folderId, null)
    }
  }

  const toggleFavorite = (document: V2DocumentPublic) => {
    if (isDemoMode || favoriteMutation.isPending) return
    favoriteMutation.mutate({
      documentId: document.id,
      favorite: !document.is_favorite,
    })
  }

  const requestDeleteDocument = (document: V2DocumentPublic) => {
    if (isDemoMode || deleteDocumentMutation.isPending) return
    setDeleteDocumentTarget(document)
  }

  const handleFolderDeleted = (folderId: string) => {
    if (selectedFolderId === folderId) {
      setSelectedFolderId("all")
    }
  }

  return (
    <DocumentDeleteContext.Provider
      value={{
        canDelete:
          !isDemoMode &&
          !deleteDocumentMutation.isPending &&
          !moveDocumentMutation.isPending,
        onDelete: requestDeleteDocument,
      }}
    >
      <section className="flex min-h-0 flex-1 flex-col gap-6 overflow-hidden">
        <div className="sticky top-0 z-20 flex shrink-0 flex-col gap-4 border-b bg-background/95 py-3 backdrop-blur lg:flex-row lg:items-end lg:justify-between">
          <h1 className="text-2xl font-semibold">Library</h1>
          <div className="flex flex-wrap items-center gap-2">
            <div
              role="tablist"
              aria-label="Document ownership"
              className="inline-flex h-9 w-fit shrink-0 items-center justify-center rounded-lg bg-muted p-[3px] text-muted-foreground"
            >
              <LibraryViewToggle
                label="Owned by you"
                active={ownershipFilter === "owned"}
                onClick={() => {
                  setOwnershipFilter("owned")
                  setSelectedFolderId("all")
                }}
              />
              <LibraryViewToggle
                label="Shared with you"
                active={ownershipFilter === "shared"}
                onClick={() => {
                  setOwnershipFilter("shared")
                  setSelectedFolderId("all")
                }}
              />
            </div>
            <div
              role="tablist"
              aria-label="Library view"
              className="inline-flex h-9 w-fit shrink-0 items-center justify-center rounded-lg bg-muted p-[3px] text-muted-foreground"
            >
              <LibraryViewToggle
                label="Files"
                active={libraryView === "files"}
                onClick={() => setLibraryView("files")}
              />
              <LibraryViewToggle
                label="Folders"
                active={libraryView === "folders"}
                onClick={() => setLibraryView("folders")}
              />
            </div>
            {!isDemoMode && (
              <>
                <Button
                  type="button"
                  size="sm"
                  className="w-fit"
                  onClick={() => setCreateDocumentOpen(true)}
                >
                  <Plus className="size-4" />
                  New document
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="w-fit"
                  onClick={() => setCreateFolderOpen(true)}
                >
                  <FolderPlus className="size-4" />
                  Create folder
                </Button>
              </>
            )}
          </div>
        </div>

        <FolderCreateDialog
          open={createFolderOpen}
          onOpenChange={setCreateFolderOpen}
          demo={isDemoMode}
          folders={folders}
          onCreated={(folder) => setSelectedFolderId(folder.id)}
        />

        <CreateDocumentDialog
          open={createDocumentOpen}
          onOpenChange={setCreateDocumentOpen}
          folders={folders}
          defaultFolderId={
            selectedFolderId !== "all" &&
            selectedFolderId !== "favorites" &&
            selectedFolderId !== "unfiled"
              ? selectedFolderId
              : null
          }
          isCreating={createDocumentMutation.isPending}
          onSubmit={(values) => createDocumentMutation.mutate(values)}
        />

        <DeleteDocumentDialog
          document={deleteDocumentTarget}
          isDeleting={deleteDocumentMutation.isPending}
          onCancel={() => setDeleteDocumentTarget(null)}
          onConfirm={(document) => deleteDocumentMutation.mutate(document.id)}
        />

        {isLoading && <LibraryLoadingSkeleton view={libraryView} />}

        {isEmpty && (
          <div className="border bg-card p-6 text-sm text-muted-foreground">
            No documents yet.
          </div>
        )}

        {!isLoading && documents.length > 0 && libraryView === "files" && (
          <div className="grid min-h-0 flex-1 gap-6 xl:grid-cols-[240px_minmax(0,1fr)]">
            <FolderNav
              folderTree={folderTree}
              selectedFolderId={selectedFolderId}
              setSelectedFolderId={setSelectedFolderId}
              allCount={documents.length}
              favoritesCount={favoriteDocuments.length}
              unfiledCount={folderCounts.unfiled}
              folderCounts={folderCounts.counts}
              loading={foldersQuery.isLoading}
              currentUserId={currentUser.id}
              demo={isDemoMode}
              onFolderDeleted={handleFolderDeleted}
            />
            <div className="min-h-0 min-w-0 overflow-y-auto pr-1">
              {isFolderEmpty && (
                <div className="border bg-card p-6 text-sm text-muted-foreground">
                  No documents in this folder.
                </div>
              )}
              {!isFolderEmpty && (
                <InfiniteDocumentGrid
                  documents={visibleDocuments}
                  canFavorite={!isDemoMode && !favoriteMutation.isPending}
                  onToggleFavorite={toggleFavorite}
                />
              )}
            </div>
          </div>
        )}

        {!isLoading &&
          (documents.length > 0 || folders.length > 0) &&
          libraryView === "folders" && (
            <div className="min-h-0 flex-1 overflow-y-auto pr-1">
              <FolderDirectory
                folderTree={folderTree}
                documentsByFolder={documentsByFolder}
                openFolderIds={openFolderIds}
                dragOverFolderId={dragOverFolderId}
                canMoveItems={canMutateLibrary}
                canFavorite={!isDemoMode && !favoriteMutation.isPending}
                currentUserId={currentUser.id}
                demo={isDemoMode}
                onToggleFolder={toggleFolderOpen}
                onFolderDragStart={(event, folder) => {
                  event.stopPropagation()
                  event.dataTransfer.effectAllowed = "move"
                  event.dataTransfer.setData(
                    "application/x-v2-folder",
                    folder.id,
                  )
                }}
                onDocumentDragStart={(event, document) => {
                  event.dataTransfer.effectAllowed = "move"
                  event.dataTransfer.setData(
                    "application/x-v2-document",
                    document.id,
                  )
                }}
                onDocumentDragEnd={() => setDragOverFolderId(null)}
                onToggleFavorite={toggleFavorite}
                onFolderDragOver={handleFolderDragOver}
                onFolderDrop={handleFolderDrop}
                onUnfiledDrop={handleUnfiledDrop}
                onRootFolderDrop={handleRootFolderDrop}
                onFolderDragLeave={() => setDragOverFolderId(null)}
                onFolderDeleted={handleFolderDeleted}
              />
            </div>
          )}
      </section>
    </DocumentDeleteContext.Provider>
  )
}

function LibraryViewToggle({
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
      className="inline-flex h-[calc(100%-1px)] min-w-20 items-center justify-center whitespace-nowrap rounded-md border border-transparent px-3 py-1 text-sm font-medium text-foreground transition-[color,box-shadow] focus-visible:border-ring focus-visible:outline-1 focus-visible:outline-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=active]:bg-background data-[state=active]:shadow-sm dark:text-muted-foreground dark:data-[state=active]:border-input dark:data-[state=active]:bg-input/30 dark:data-[state=active]:text-foreground"
    >
      {label}
    </button>
  )
}

function FolderNav({
  folderTree,
  selectedFolderId,
  setSelectedFolderId,
  allCount,
  favoritesCount,
  unfiledCount,
  folderCounts,
  loading,
  currentUserId,
  demo,
  onFolderDeleted,
}: {
  folderTree: FolderTreeNode[]
  selectedFolderId: string
  setSelectedFolderId: (folderId: string) => void
  allCount: number
  favoritesCount: number
  unfiledCount: number
  folderCounts: Map<string, number>
  loading: boolean
  currentUserId: string
  demo: boolean
  onFolderDeleted: (folderId: string) => void
}) {
  return (
    <nav
      aria-label="Library folders"
      className="min-w-0 self-start border bg-card p-2 text-sm xl:h-full xl:overflow-y-auto"
    >
      <FolderNavButton
        active={selectedFolderId === "all"}
        label="All documents"
        count={allCount}
        icon={<FileText className="size-4" />}
        onClick={() => setSelectedFolderId("all")}
      />
      <FolderNavButton
        active={selectedFolderId === "favorites"}
        label="Favorites"
        count={favoritesCount}
        icon={<Star className="size-4" />}
        onClick={() => setSelectedFolderId("favorites")}
      />
      <FolderNavButton
        active={selectedFolderId === "unfiled"}
        label="Unfiled"
        count={unfiledCount}
        icon={<Folder className="size-4" />}
        onClick={() => setSelectedFolderId("unfiled")}
      />
      <div className="my-2 border-t" />
      {loading && (
        <div className="px-2 py-2 text-xs text-muted-foreground">
          Loading folders…
        </div>
      )}
      {!loading && (
        <FolderNavTree
          nodes={folderTree}
          selectedFolderId={selectedFolderId}
          setSelectedFolderId={setSelectedFolderId}
          folderCounts={folderCounts}
          currentUserId={currentUserId}
          demo={demo}
          onFolderDeleted={onFolderDeleted}
        />
      )}
    </nav>
  )
}

function FolderNavTree({
  nodes,
  selectedFolderId,
  setSelectedFolderId,
  folderCounts,
  currentUserId,
  demo,
  onFolderDeleted,
  depth = 0,
}: {
  nodes: FolderTreeNode[]
  selectedFolderId: string
  setSelectedFolderId: (folderId: string) => void
  folderCounts: Map<string, number>
  currentUserId: string
  demo: boolean
  onFolderDeleted: (folderId: string) => void
  depth?: number
}) {
  return (
    <>
      {nodes.map((node) => (
        <div key={node.folder.id}>
          <FolderNavButton
            active={selectedFolderId === node.folder.id}
            label={node.folder.name}
            count={folderCounts.get(node.folder.id) ?? 0}
            depth={depth}
            icon={<Folder className="size-4" />}
            visibility={node.folder.visibility}
            onClick={() => setSelectedFolderId(node.folder.id)}
            action={
              node.folder.owner_id === currentUserId ? (
                <FolderActionsMenu
                  folder={node.folder}
                  demo={demo}
                  onDeleted={onFolderDeleted}
                />
              ) : undefined
            }
          />
          {node.children.length > 0 && (
            <FolderNavTree
              nodes={node.children}
              selectedFolderId={selectedFolderId}
              setSelectedFolderId={setSelectedFolderId}
              folderCounts={folderCounts}
              currentUserId={currentUserId}
              demo={demo}
              onFolderDeleted={onFolderDeleted}
              depth={depth + 1}
            />
          )}
        </div>
      ))}
    </>
  )
}

function FolderNavButton({
  active,
  label,
  count,
  depth = 0,
  icon,
  visibility,
  action,
  onClick,
}: {
  active: boolean
  label: string
  count: number
  depth?: number
  icon: ReactNode
  visibility?: V2DocumentVisibility
  action?: ReactNode
  onClick: () => void
}) {
  return (
    <div
      className={cn(
        "flex w-full items-center rounded-md transition-colors hover:bg-muted",
        active && "bg-muted text-foreground",
      )}
    >
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-2 px-2 py-2 text-left"
        style={{ paddingLeft: `${8 + depth * 16}px` }}
        onClick={onClick}
      >
        <span className="shrink-0 text-muted-foreground">{icon}</span>
        <span className="min-w-0 flex-1 truncate">{label}</span>
        {visibility === "organization" && (
          <Building2 className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="shrink-0 text-xs text-muted-foreground">{count}</span>
      </button>
      {action && <div className="pr-1">{action}</div>}
    </div>
  )
}

function FolderDirectory({
  folderTree,
  documentsByFolder,
  openFolderIds,
  dragOverFolderId,
  canMoveItems,
  canFavorite,
  currentUserId,
  demo,
  onToggleFolder,
  onFolderDragStart,
  onDocumentDragStart,
  onDocumentDragEnd,
  onToggleFavorite,
  onFolderDragOver,
  onFolderDrop,
  onUnfiledDrop,
  onRootFolderDrop,
  onFolderDragLeave,
  onFolderDeleted,
}: {
  folderTree: FolderTreeNode[]
  documentsByFolder: Map<string, V2DocumentPublic[]>
  openFolderIds: Set<string>
  dragOverFolderId: DirectoryDropTargetId | null
  canMoveItems: boolean
  canFavorite: boolean
  currentUserId: string
  demo: boolean
  onToggleFolder: (folderId: string) => void
  onFolderDragStart: (
    event: DragEvent<HTMLButtonElement>,
    folder: V2DocumentFolderPublic,
  ) => void
  onDocumentDragStart: (
    event: DragEvent<HTMLAnchorElement>,
    document: V2DocumentPublic,
  ) => void
  onDocumentDragEnd: () => void
  onToggleFavorite: (document: V2DocumentPublic) => void
  onFolderDragOver: (
    event: DragEvent<HTMLElement>,
    folderId: DirectoryDropTargetId,
  ) => void
  onFolderDrop: (event: DragEvent<HTMLElement>, folderId: string | null) => void
  onUnfiledDrop: (event: DragEvent<HTMLElement>) => void
  onRootFolderDrop: (event: DragEvent<HTMLElement>) => void
  onFolderDragLeave: () => void
  onFolderDeleted: (folderId: string) => void
}) {
  const favoriteDocuments = documentsByFolder.get("favorites") ?? []
  const unfiledDocuments = documentsByFolder.get("unfiled") ?? []

  return (
    <section
      aria-label="Library contents"
      className={cn(
        "min-w-0 border bg-card text-card-foreground",
        dragOverFolderId === "root" && "bg-muted/40",
      )}
      onDragOver={(event) => onFolderDragOver(event, "root")}
      onDrop={onRootFolderDrop}
      onDragLeave={onFolderDragLeave}
    >
      <DirectoryUnfiled
        label="Favorites"
        icon={<Star className="size-4 shrink-0 text-muted-foreground" />}
        documents={favoriteDocuments}
        open={openFolderIds.has("favorites")}
        dragOver={false}
        canMoveItems={false}
        canFavorite={canFavorite}
        onToggle={() => onToggleFolder("favorites")}
        onDocumentDragStart={onDocumentDragStart}
        onDocumentDragEnd={onDocumentDragEnd}
        onToggleFavorite={onToggleFavorite}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => event.preventDefault()}
        onDragLeave={onFolderDragLeave}
      />
      <DirectoryUnfiled
        label="Unfiled"
        icon={<Folder className="size-4 shrink-0 text-muted-foreground" />}
        documents={unfiledDocuments}
        open={openFolderIds.has("unfiled")}
        dragOver={dragOverFolderId === "unfiled"}
        canMoveItems={canMoveItems}
        canFavorite={canFavorite}
        onToggle={() => onToggleFolder("unfiled")}
        onDocumentDragStart={onDocumentDragStart}
        onDocumentDragEnd={onDocumentDragEnd}
        onToggleFavorite={onToggleFavorite}
        onDragOver={(event) => onFolderDragOver(event, "unfiled")}
        onDrop={onUnfiledDrop}
        onDragLeave={onFolderDragLeave}
      />
      <DirectoryFolderTree
        nodes={folderTree}
        documentsByFolder={documentsByFolder}
        openFolderIds={openFolderIds}
        dragOverFolderId={dragOverFolderId}
        canMoveItems={canMoveItems}
        canFavorite={canFavorite}
        currentUserId={currentUserId}
        demo={demo}
        onToggleFolder={onToggleFolder}
        onFolderDragStart={onFolderDragStart}
        onDocumentDragStart={onDocumentDragStart}
        onDocumentDragEnd={onDocumentDragEnd}
        onToggleFavorite={onToggleFavorite}
        onFolderDragOver={onFolderDragOver}
        onFolderDrop={onFolderDrop}
        onFolderDragLeave={onFolderDragLeave}
        onFolderDeleted={onFolderDeleted}
      />
    </section>
  )
}

function DirectoryFolderTree({
  nodes,
  documentsByFolder,
  openFolderIds,
  dragOverFolderId,
  canMoveItems,
  canFavorite,
  currentUserId,
  demo,
  onToggleFolder,
  onFolderDragStart,
  onDocumentDragStart,
  onDocumentDragEnd,
  onToggleFavorite,
  onFolderDragOver,
  onFolderDrop,
  onFolderDragLeave,
  onFolderDeleted,
  depth = 0,
}: {
  nodes: FolderTreeNode[]
  documentsByFolder: Map<string, V2DocumentPublic[]>
  openFolderIds: Set<string>
  dragOverFolderId: DirectoryDropTargetId | null
  canMoveItems: boolean
  canFavorite: boolean
  currentUserId: string
  demo: boolean
  onToggleFolder: (folderId: string) => void
  onFolderDragStart: (
    event: DragEvent<HTMLButtonElement>,
    folder: V2DocumentFolderPublic,
  ) => void
  onDocumentDragStart: (
    event: DragEvent<HTMLAnchorElement>,
    document: V2DocumentPublic,
  ) => void
  onDocumentDragEnd: () => void
  onToggleFavorite: (document: V2DocumentPublic) => void
  onFolderDragOver: (
    event: DragEvent<HTMLElement>,
    folderId: DirectoryDropTargetId,
  ) => void
  onFolderDrop: (event: DragEvent<HTMLElement>, folderId: string | null) => void
  onFolderDragLeave: () => void
  onFolderDeleted: (folderId: string) => void
  depth?: number
}) {
  return (
    <>
      {nodes.map((node) => (
        <DirectoryFolder
          key={node.folder.id}
          node={node}
          documents={documentsByFolder.get(node.folder.id) ?? []}
          open={openFolderIds.has(node.folder.id)}
          dragOver={dragOverFolderId === node.folder.id}
          canMoveItems={canMoveItems}
          canFavorite={canFavorite}
          currentUserId={currentUserId}
          demo={demo}
          depth={depth}
          onToggle={() => onToggleFolder(node.folder.id)}
          onFolderDragStart={onFolderDragStart}
          onDocumentDragStart={onDocumentDragStart}
          onDocumentDragEnd={onDocumentDragEnd}
          onToggleFavorite={onToggleFavorite}
          onDragOver={(event) => onFolderDragOver(event, node.folder.id)}
          onDrop={(event) => onFolderDrop(event, node.folder.id)}
          onDragLeave={onFolderDragLeave}
          onFolderDeleted={onFolderDeleted}
          renderChildren={() => (
            <DirectoryFolderTree
              nodes={node.children}
              documentsByFolder={documentsByFolder}
              openFolderIds={openFolderIds}
              dragOverFolderId={dragOverFolderId}
              canMoveItems={canMoveItems}
              canFavorite={canFavorite}
              currentUserId={currentUserId}
              demo={demo}
              onToggleFolder={onToggleFolder}
              onFolderDragStart={onFolderDragStart}
              onDocumentDragStart={onDocumentDragStart}
              onDocumentDragEnd={onDocumentDragEnd}
              onToggleFavorite={onToggleFavorite}
              onFolderDragOver={onFolderDragOver}
              onFolderDrop={onFolderDrop}
              onFolderDragLeave={onFolderDragLeave}
              onFolderDeleted={onFolderDeleted}
              depth={depth + 1}
            />
          )}
        />
      ))}
    </>
  )
}

function DirectoryUnfiled({
  label,
  icon,
  documents,
  open,
  dragOver,
  canMoveItems,
  canFavorite,
  onToggle,
  onDocumentDragStart,
  onDocumentDragEnd,
  onToggleFavorite,
  onDragOver,
  onDrop,
  onDragLeave,
}: {
  label: string
  icon: ReactNode
  documents: V2DocumentPublic[]
  open: boolean
  dragOver: boolean
  canMoveItems: boolean
  canFavorite: boolean
  onToggle: () => void
  onDocumentDragStart: (
    event: DragEvent<HTMLAnchorElement>,
    document: V2DocumentPublic,
  ) => void
  onDocumentDragEnd: () => void
  onToggleFavorite: (document: V2DocumentPublic) => void
  onDragOver: (event: DragEvent<HTMLElement>) => void
  onDrop: (event: DragEvent<HTMLElement>) => void
  onDragLeave: () => void
}) {
  return (
    <fieldset
      aria-label={`${label} documents`}
      className={cn("border-b last:border-b-0", dragOver && "bg-muted/70")}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragLeave={onDragLeave}
    >
      <button
        type="button"
        className="flex h-11 w-full items-center gap-2 px-3 text-left text-sm hover:bg-muted"
        onClick={onToggle}
      >
        {open ? (
          <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
        )}
        {icon}
        <span className="min-w-0 flex-1 truncate font-medium">{label}</span>
        <span className="shrink-0 text-xs text-muted-foreground">
          {documents.length}
        </span>
      </button>
      {open && (
        <div className="pb-2">
          {documents.length === 0 && (
            <div className="ml-12 px-3 py-2 text-sm text-muted-foreground">
              Empty folder
            </div>
          )}
          {documents.map((document) => (
            <DirectoryDocumentRow
              key={document.id}
              document={document}
              depth={0}
              draggable={canMoveItems}
              canFavorite={canFavorite}
              onDragStart={onDocumentDragStart}
              onDragEnd={onDocumentDragEnd}
              onToggleFavorite={onToggleFavorite}
            />
          ))}
        </div>
      )}
    </fieldset>
  )
}

function DirectoryFolder({
  node,
  documents,
  open,
  dragOver,
  canMoveItems,
  canFavorite,
  currentUserId,
  demo,
  depth,
  onToggle,
  onFolderDragStart,
  onDocumentDragStart,
  onDocumentDragEnd,
  onToggleFavorite,
  onDragOver,
  onDrop,
  onDragLeave,
  onFolderDeleted,
  renderChildren,
}: {
  node: FolderTreeNode
  documents: V2DocumentPublic[]
  open: boolean
  dragOver: boolean
  canMoveItems: boolean
  canFavorite: boolean
  currentUserId: string
  demo: boolean
  depth: number
  onToggle: () => void
  onFolderDragStart: (
    event: DragEvent<HTMLButtonElement>,
    folder: V2DocumentFolderPublic,
  ) => void
  onDocumentDragStart: (
    event: DragEvent<HTMLAnchorElement>,
    document: V2DocumentPublic,
  ) => void
  onDocumentDragEnd: () => void
  onToggleFavorite: (document: V2DocumentPublic) => void
  onDragOver: (event: DragEvent<HTMLElement>) => void
  onDrop: (event: DragEvent<HTMLElement>) => void
  onDragLeave: () => void
  onFolderDeleted: (folderId: string) => void
  renderChildren: () => ReactNode
}) {
  const childCount = node.children.length
  const itemCount = childCount + documents.length

  return (
    <fieldset
      aria-label={`${node.folder.name} folder`}
      className={cn("border-b last:border-b-0", dragOver && "bg-muted/70")}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragLeave={onDragLeave}
    >
      <div className="flex items-center hover:bg-muted">
        <button
          type="button"
          draggable={canMoveItems}
          className={cn(
            "flex h-11 min-w-0 flex-1 items-center gap-2 px-3 text-left text-sm",
            canMoveItems && "cursor-grab active:cursor-grabbing",
          )}
          style={{ paddingLeft: `${12 + depth * 24}px` }}
          onClick={onToggle}
          onDragStart={(event) => onFolderDragStart(event, node.folder)}
        >
          {open ? (
            <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
          )}
          {open ? (
            <FolderOpen className="size-4 shrink-0 text-muted-foreground" />
          ) : (
            <Folder className="size-4 shrink-0 text-muted-foreground" />
          )}
          <span className="min-w-0 flex-1 truncate font-medium">
            {node.folder.name}
          </span>
          {node.folder.visibility === "organization" && (
            <Building2 className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="shrink-0 text-xs text-muted-foreground">
            {itemCount}
          </span>
        </button>
        {node.folder.owner_id === currentUserId && (
          <div className="pr-2">
            <FolderActionsMenu
              folder={node.folder}
              demo={demo}
              onDeleted={onFolderDeleted}
            />
          </div>
        )}
      </div>
      {open && (
        <div className="pb-2">
          {itemCount === 0 && (
            <div
              className="px-3 py-2 text-sm text-muted-foreground"
              style={{ marginLeft: `${24 + depth * 24}px` }}
            >
              Empty folder
            </div>
          )}
          {childCount > 0 && renderChildren()}
          {documents.map((document) => (
            <DirectoryDocumentRow
              key={document.id}
              document={document}
              depth={depth + 1}
              draggable={canMoveItems}
              canFavorite={canFavorite}
              onDragStart={onDocumentDragStart}
              onDragEnd={onDocumentDragEnd}
              onToggleFavorite={onToggleFavorite}
            />
          ))}
        </div>
      )}
    </fieldset>
  )
}

function DirectoryDocumentRow({
  document,
  depth,
  draggable,
  canFavorite,
  onDragStart,
  onDragEnd,
  onToggleFavorite,
}: {
  document: V2DocumentPublic
  depth: number
  draggable: boolean
  canFavorite: boolean
  onDragStart: (
    event: DragEvent<HTMLAnchorElement>,
    document: V2DocumentPublic,
  ) => void
  onDragEnd: () => void
  onToggleFavorite: (document: V2DocumentPublic) => void
}) {
  const { canDelete, onDelete } = useDocumentDelete()
  return (
    <div className="flex items-center hover:bg-muted">
      <Link
        to="/v2/library/$documentId"
        params={{ documentId: document.id }}
        draggable={draggable}
        onDragStart={(event) => onDragStart(event, document)}
        onDragEnd={onDragEnd}
        className={cn(
          "grid min-h-10 min-w-0 flex-1 grid-cols-[minmax(0,1fr)_160px_130px] items-center gap-3 px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring max-md:grid-cols-[minmax(0,1fr)]",
          draggable && "cursor-grab active:cursor-grabbing",
        )}
        style={{ marginLeft: `${24 + depth * 24}px` }}
      >
        <span className="flex min-w-0 items-center gap-2">
          <FileText className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate font-medium">{document.title}</span>
        </span>
        <span className="truncate text-xs text-muted-foreground max-md:hidden">
          {document.visibility === "organization" ? "Organization" : "Private"}
        </span>
        <span className="truncate text-xs text-muted-foreground max-md:hidden">
          {formatDateOnly(document.updated_at)}
        </span>
      </Link>
      <FavoriteButton
        document={document}
        disabled={!canFavorite}
        onToggle={onToggleFavorite}
      />
      {canDelete && (
        <DocumentActionsMenu document={document} onDelete={onDelete} />
      )}
    </div>
  )
}

function FavoriteButton({
  document,
  disabled,
  onToggle,
}: {
  document: V2DocumentPublic
  disabled: boolean
  onToggle: (document: V2DocumentPublic) => void
}) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      disabled={disabled}
      aria-label={document.is_favorite ? "Remove favorite" : "Add favorite"}
      onClick={(event) => {
        event.preventDefault()
        event.stopPropagation()
        onToggle(document)
      }}
    >
      <Star
        className={cn(
          "size-4",
          document.is_favorite
            ? "fill-yellow-400 text-yellow-500"
            : "text-muted-foreground",
        )}
      />
    </Button>
  )
}

function DocumentCard({
  document,
  canFavorite,
  onToggleFavorite,
}: {
  document: V2DocumentPublic
  canFavorite: boolean
  onToggleFavorite: (document: V2DocumentPublic) => void
}) {
  const { canDelete, onDelete } = useDocumentDelete()
  const sharedCount = document.shared_with?.length ?? 0
  return (
    <Link
      to="/v2/library/$documentId"
      params={{ documentId: document.id }}
      className="flex min-h-[320px] flex-col border bg-card p-5 text-card-foreground transition-colors hover:border-sidebar-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sidebar-ring"
    >
      <div className="flex items-start">
        <FileText className="mt-1 size-5 shrink-0 text-muted-foreground" />
        <div className="ml-auto flex flex-wrap justify-end gap-1.5">
          <FavoriteButton
            document={document}
            disabled={!canFavorite}
            onToggle={onToggleFavorite}
          />
          {canDelete && (
            <DocumentActionsMenu document={document} onDelete={onDelete} />
          )}
          {document.visibility === "organization" && (
            <Badge variant="outline">
              <Building2 className="size-3" />
              Org
            </Badge>
          )}
          {sharedCount > 0 && (
            <Badge variant="secondary">
              <Share2 className="size-3" />
              {sharedCount}
            </Badge>
          )}
        </div>
      </div>

      <div className="mt-4">
        <h2 className="text-base font-semibold leading-6">{document.title}</h2>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">
          {document.description}
        </p>
      </div>

      <dl className="mt-5 grid gap-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <Folder className="size-4" />
          <dt className="sr-only">Folder</dt>
          <dd>{document.folder_name ?? "Unfiled"}</dd>
        </div>
        <div className="flex items-center gap-2">
          <CalendarDays className="size-4" />
          <dt className="sr-only">Updated</dt>
          <dd>
            Created {formatDateOnly(document.created_at)} - Updated{" "}
            {formatDateOnly(document.updated_at)}
          </dd>
        </div>
        <div className="flex items-center gap-2">
          <Users className="size-4" />
          <dt className="sr-only">Access</dt>
          <dd>
            {sharedCount > 0
              ? `${sharedCount} shared member${sharedCount === 1 ? "" : "s"}`
              : "Private"}
          </dd>
        </div>
      </dl>
    </Link>
  )
}

function DocumentActionsMenu({
  document,
  onDelete,
}: {
  document: V2DocumentPublic
  onDelete: (document: V2DocumentPublic) => void
}) {
  const queryClient = useQueryClient()
  const { showSuccessToast, showErrorToast } = useCustomToast()
  const [renameOpen, setRenameOpen] = useState(false)
  const [renameValue, setRenameValue] = useState(document.title)

  const canRename =
    !document.is_demo &&
    (document.user_access === "owner" || document.user_access === "editor")

  const renameMutation = useMutation({
    mutationFn: (title: string) =>
      updateV2Document(document.id, { title }, { demo: document.is_demo }),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["v2-documents", { demo: document.is_demo }],
      })
      queryClient.invalidateQueries({
        queryKey: ["v2-document-folders", { demo: document.is_demo }],
      })
      setRenameOpen(false)
      showSuccessToast("Document renamed.")
    },
    onError: () => {
      showErrorToast("Could not rename document.")
    },
  })

  const submitRename = (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = renameValue.trim()
    if (!trimmed || trimmed === document.title || !canRename) return
    renameMutation.mutate(trimmed)
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            aria-label={`Open options for ${document.title}`}
            className="cursor-pointer"
            onClick={(event) => {
              event.preventDefault()
              event.stopPropagation()
            }}
            onDragStart={(event) => event.preventDefault()}
          >
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent
          align="end"
          className="w-44"
          onClick={(event) => event.stopPropagation()}
        >
          {canRename && (
            <DropdownMenuItem
              className="cursor-pointer"
              onClick={(event) => event.stopPropagation()}
              onSelect={() => {
                setRenameValue(document.title)
                setRenameOpen(true)
              }}
            >
              <Pencil className="size-4" />
              Rename document
            </DropdownMenuItem>
          )}
          <DropdownMenuItem
            variant="destructive"
            className="cursor-pointer"
            onClick={(event) => event.stopPropagation()}
            onSelect={() => onDelete(document)}
          >
            <Trash2 className="size-4" />
            Delete document
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={renameOpen} onOpenChange={setRenameOpen}>
        <DialogContent
          className="sm:max-w-md"
          onClick={(event) => event.stopPropagation()}
        >
          <DialogHeader>
            <DialogTitle>Rename document</DialogTitle>
            <DialogDescription>
              Update the document title shown in your library.
            </DialogDescription>
          </DialogHeader>
          <form className="space-y-4" onSubmit={submitRename}>
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor={`rename-document-${document.id}`}
              >
                Document title
              </label>
              <Input
                id={`rename-document-${document.id}`}
                value={renameValue}
                onChange={(event) => setRenameValue(event.target.value)}
                autoFocus
              />
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                disabled={renameMutation.isPending}
                onClick={() => setRenameOpen(false)}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                disabled={
                  !renameValue.trim() ||
                  renameValue.trim() === document.title ||
                  !canRename ||
                  renameMutation.isPending
                }
              >
                {renameMutation.isPending ? "Renaming…" : "Rename"}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  )
}

function CreateDocumentDialog({
  open,
  onOpenChange,
  folders,
  defaultFolderId,
  isCreating,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  folders: V2DocumentFolderPublic[]
  defaultFolderId: string | null
  isCreating: boolean
  onSubmit: (values: { title: string; folderId: string | null }) => void
}) {
  const [title, setTitle] = useState("")
  const [folderId, setFolderId] = useState<string | null>(defaultFolderId)

  useEffect(() => {
    if (open) {
      setTitle("")
      setFolderId(defaultFolderId)
    }
  }, [open, defaultFolderId])

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || isCreating) return
    onSubmit({ title: trimmed, folderId })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New document</DialogTitle>
          <DialogDescription>
            Start a blank document in your library. Open it to write the
            content.
          </DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={handleSubmit}>
          <div className="space-y-2">
            <label className="text-sm font-medium" htmlFor="new-document-title">
              Title
            </label>
            <Input
              id="new-document-title"
              autoFocus
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="Untitled document"
            />
          </div>
          <div className="space-y-2">
            <span className="text-sm font-medium">Folder</span>
            <FolderPickerDropdown
              folders={folders}
              currentFolderId={folderId}
              onSelect={setFolderId}
              onCreateFolder={() => {}}
              triggerLabel={
                folderId
                  ? (folders.find((folder) => folder.id === folderId)?.name ??
                    "Unfiled")
                  : "Unfiled"
              }
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              disabled={isCreating}
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!title.trim() || isCreating}>
              <Plus className="size-4" />
              {isCreating ? "Creating" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteDocumentDialog({
  document,
  isDeleting,
  onCancel,
  onConfirm,
}: {
  document: V2DocumentPublic | null
  isDeleting: boolean
  onCancel: () => void
  onConfirm: (document: V2DocumentPublic) => void
}) {
  return (
    <Dialog
      open={document !== null}
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Delete document?</DialogTitle>
          <DialogDescription>
            This permanently removes “{document?.title}” from your library.
            Anyone it was shared with will lose access.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            disabled={isDeleting}
            onClick={onCancel}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            disabled={!document || isDeleting}
            onClick={() => document && onConfirm(document)}
          >
            {isDeleting ? "Deleting" : "Delete document"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function LibraryLoadingSkeleton({ view }: { view: "files" | "folders" }) {
  if (view === "folders") {
    return (
      <div className="space-y-px border bg-card p-2">
        {Array.from({ length: 6 }).map((_, idx) => (
          <Skeleton key={idx} className="h-10 w-full rounded-sm" />
        ))}
      </div>
    )
  }
  return (
    <div className="grid gap-6 xl:grid-cols-[240px_minmax(0,1fr)]">
      <div className="space-y-2 border bg-card p-3">
        {Array.from({ length: 5 }).map((_, idx) => (
          <Skeleton key={idx} className="h-8 w-full rounded-sm" />
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {Array.from({ length: 6 }).map((_, idx) => (
          <div
            key={idx}
            className="flex min-h-[320px] flex-col gap-4 border bg-card p-5"
          >
            <Skeleton className="h-5 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="mt-auto h-3 w-1/2" />
          </div>
        ))}
      </div>
    </div>
  )
}

function InfiniteDocumentGrid({
  documents,
  canFavorite,
  onToggleFavorite,
}: {
  documents: V2DocumentPublic[]
  canFavorite: boolean
  onToggleFavorite: (document: V2DocumentPublic) => void
}) {
  const [renderedCount, setRenderedCount] = useState(FILES_PAGE_SIZE)
  const sentinelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    setRenderedCount((current) =>
      Math.min(
        Math.max(current, FILES_PAGE_SIZE),
        documents.length || FILES_PAGE_SIZE,
      ),
    )
  }, [documents.length])

  const loadMore = useCallback(() => {
    setRenderedCount((current) =>
      Math.min(current + FILES_PAGE_SIZE, documents.length),
    )
  }, [documents.length])

  useEffect(() => {
    const node = sentinelRef.current
    if (!node) return
    if (renderedCount >= documents.length) return
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            loadMore()
          }
        }
      },
      { rootMargin: "200px" },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [loadMore, renderedCount, documents.length])

  const visible = documents.slice(0, renderedCount)
  const remaining = documents.length - visible.length

  return (
    <div>
      <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
        {visible.map((document) => (
          <DocumentCard
            key={document.id}
            document={document}
            canFavorite={canFavorite}
            onToggleFavorite={onToggleFavorite}
          />
        ))}
      </div>
      {remaining > 0 && (
        <div
          ref={sentinelRef}
          className="mt-6 flex items-center justify-center py-4 text-xs text-muted-foreground"
        >
          Loading {Math.min(FILES_PAGE_SIZE, remaining)} more…
        </div>
      )}
    </div>
  )
}
