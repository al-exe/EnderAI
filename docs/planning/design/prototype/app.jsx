/* global React, ReactDOM, renderMarkdown */
/** Taskforce Document Prototype */

const { useState, useRef, useEffect, useCallback, useMemo } = React
const e = React.createElement
const doc = window.SAMPLE_DOC

/* ===================================================================
   Helpers
   =================================================================== */
function fmt(n) { return n.toLocaleString() }

function findSection(id) {
  return doc.details_markdown_sections.find((s) => s.anchor_id === id)
}

// All anchor IDs cited from summary, in source order
const SUMMARY_CITES = (() => {
  const seen = new Set(), arr = []
  doc.main_body.forEach((p) => p.segments && p.segments.forEach((s) => {
    if (s.anchor_id && !seen.has(s.anchor_id)) { seen.add(s.anchor_id); arr.push(s.anchor_id) }
  }))
  return arr
})()

// Compute backrefs: for each details section, which summary paragraphs cite it
function backrefsFor(anchorId) {
  const cites = []
  doc.main_body.forEach((p, pi) => {
    if (!p.segments) return
    const hasIt = p.segments.some((s) => s.anchor_id === anchorId)
    if (hasIt) cites.push({ pi, kind: p.kind })
  })
  return cites
}

/* ===================================================================
   Top app bar
   =================================================================== */
function AppBar() {
  return e("div", { className: "appbar" },
    e("div", { className: "brand" }, e("span", { className: "mk" }), "Taskforce"),
    e("div", { className: "crumb" },
      e("a", { href: "#" }, "Library"),
      e("span", { className: "sep" }, "/"),
      e("a", { href: "#" }, "Billing"),
      e("span", { className: "sep" }, "/"),
      e("span", { className: "here" }, doc.title),
    ),
    e("div", { className: "sp" }),
    e("div", { className: "search" }, "/", "  Jump to anything"),
  )
}

/* ===================================================================
   Doc header — title, owners, view + edit toggles
   =================================================================== */
function DocHeader({ viewMode, setViewMode, isEditing, setIsEditing, anchorMode, setAnchorMode }) {
  return e("div", { className: "dochead" },
    e("div", { className: "left" },
      e("div", { className: "crumb" }, "Document · ", doc.reuse.count, " reuses · last 2h ago"),
      e("h1", null, doc.title),
      e("p", { className: "desc" }, doc.description),
      e("div", { className: "meta-row" },
        e("span", { className: "chip scope-org" }, "Organization"),
        e("span", null, "by ", e("b", null, doc.author.name), " · ", doc.author.handle),
        e("span", null, "updated ", e("b", null, "2h ago")),
        e("span", null, e("b", { style: { color: "var(--primary)" } }, fmt(doc.reuse.tokens_saved)), " tokens saved (", doc.reuse.count, " reuses)"),
        e("span", { className: "avs" },
          ...doc.shared_with.map((a, i) => e("span", { key: i, className: "av", style: { color: "white", background: a.color } }, a.initials)),
        ),
      )
    ),
    e("div", { className: "right" },
      e("div", { className: "row gap-2" },
        // edit toggle
        e("button", {
          className: `btn ${isEditing ? "solid" : ""}`,
          onClick: () => {
            setIsEditing(!isEditing)
            if (isEditing) setAnchorMode(false)
          }
        }, isEditing ? "▍ Editing" : "✎ Edit"),
        // anchor mode (only meaningful in split + editing)
        e("button", {
          className: `btn ${anchorMode ? "primary" : ""}`,
          disabled: !isEditing || viewMode !== "split",
          style: { opacity: (!isEditing || viewMode !== "split") ? 0.4 : 1 },
          onClick: () => setAnchorMode(!anchorMode),
          title: viewMode !== "split" ? "Switch to Split view first" : isEditing ? "Toggle anchor mode" : "Enter edit mode first",
        }, "⌘ ", "Anchor"),
        e("button", { className: "btn ghost" }, "↗ Share"),
      ),
      e("div", { className: "seg" },
        ...[
          ["summary",  "Summary"],
          ["split",    "Split"],
          ["details",  "Details"],
        ].map(([k, l]) => e("div", {
          key: k,
          className: `opt ${viewMode === k ? "on" : ""}`,
          onClick: () => setViewMode(k),
        }, l)),
      ),
    )
  )
}

/* ===================================================================
   Toolbar (Editor mode)
   =================================================================== */
function Toolbar({ savedAt }) {
  const G = ({ children }) => e("div", { className: "group" }, children)
  const B = ({ icon, on, title }) => e("button", { className: on ? "on" : "", title }, icon)
  return e("div", { className: "toolbar" },
    e(G, null,
      e(B, { icon: "H1", title: "Heading 1" }),
      e(B, { icon: "H2", title: "Heading 2" }),
      e(B, { icon: "P", title: "Paragraph" }),
    ),
    e(G, null,
      e(B, { icon: e("b", null, "B"), title: "Bold (⌘B)" }),
      e(B, { icon: e("i", null, "I"), title: "Italic (⌘I)" }),
      e(B, { icon: e("span", { style: { textDecoration: "line-through" }}, "S"), title: "Strikethrough" }),
      e(B, { icon: "‹/›", title: "Inline code" }),
    ),
    e(G, null,
      e(B, { icon: "🔗".replace("🔗", "⛓"), title: "Link" }),
      e(B, { icon: "§", title: "Add anchor citation — requires Anchor mode" }),
    ),
    e("div", { className: "saved" }, e("span", { className: "dot" }), "Auto-saved · ", savedAt)
  )
}

/* ===================================================================
   Summary pane — renders main_body
   =================================================================== */
function SummaryPane({ isEditing, anchorMode, activeAnchor, onCiteClick, onCiteHover, onPickSummary, summaryPick, hoverPoint }) {
  function renderSegment(seg, k) {
    if (seg.anchor_id) {
      const short = seg.anchor_short
      const isLast = !!short // segment with `anchor_short` is the "cite marker carrier"
      return e(React.Fragment, { key: k },
        // the citation underline span (the text), plus the §N marker
        e("span", { style: { borderBottom: "1px dotted var(--primary-line)", color: "var(--fg-soft)" } }, seg.text),
        short && e("span", {
          className: `cite ${activeAnchor === seg.anchor_id ? "active" : ""}`,
          onClick: (ev) => { ev.stopPropagation(); onCiteClick(seg.anchor_id) },
          onMouseEnter: (ev) => onCiteHover(seg.anchor_id, ev.currentTarget),
          onMouseLeave: () => onCiteHover(null),
          "data-cite": seg.anchor_id,
        }, e("span", { className: "glyph" }, "§"), short.replace("§", "")),
      )
    }
    if (seg.code) return e("code", { key: k }, seg.text)
    if (seg.bold) return e("strong", { key: k }, seg.text)
    if (seg.italic) return e("em", { key: k }, seg.text)
    return e(React.Fragment, { key: k }, seg.text)
  }

  function renderParagraph(p, i) {
    const inner = (p.segments || []).map((s, j) => renderSegment(s, `${i}-${j}`))
    if (p.kind === "h1") return e("h1", { key: i, contentEditable: isEditing, suppressContentEditableWarning: true }, inner)
    if (p.kind === "h2") return e("h2", { key: i, contentEditable: isEditing, suppressContentEditableWarning: true }, inner)
    return e("p", { key: i, contentEditable: isEditing, suppressContentEditableWarning: true }, inner)
  }

  return e("div", { className: "pane summary-pane" },
    e("div", { className: "pane-head" },
      e("div", { className: "ttl" }, e("span", { className: "dot" }), e("b", null, "Summary"), " · human + AI"),
      e("div", { className: "row gap-2" },
        e("span", { className: "kbd", title: "Sections cited" }, SUMMARY_CITES.length, " citations"),
      )
    ),
    e("div", { className: "pane-body" },
      isEditing && e(Toolbar, { savedAt: "2:14 PM" }),
      e("div", { className: `summary-content ${isEditing ? "editing" : ""}` },
        doc.main_body.map(renderParagraph)
      ),
      // hover popover (positioned relative to viewport)
      hoverPoint && e("div", {
        className: "cite-pop",
        style: { left: hoverPoint.x + "px", top: hoverPoint.y + "px" },
      }, e(CitePopBody, { anchorId: hoverPoint.id }))
    ),
  )
}

function CitePopBody({ anchorId }) {
  const sec = findSection(anchorId)
  if (!sec) return null
  // First ~140 chars of the section's first paragraph (skipping heading)
  const lines = sec.markdown.split("\n").filter((l) => l.trim() && !l.startsWith("#"))
  const preview = lines[0]?.slice(0, 200) || ""
  return e(React.Fragment, null,
    e("div", { className: "hd" }, sec.title),
    e("div", { className: "body" }, renderMarkdown(preview, `pop-${anchorId}`)),
    e("div", { className: "ft" }, "click · open in details   ·   ⌥click · open in split")
  )
}

/* ===================================================================
   Details outline (rail)
   =================================================================== */
function Outline({ activeAnchor, onJump, compact = false }) {
  return e("aside", { className: "outline" },
    e("div", { className: "head" }, "On this page"),
    e("ul", null,
      doc.details_markdown_sections.map((s) =>
        e("li", { key: s.anchor_id, className: activeAnchor === s.anchor_id ? "active" : "" },
          e("a", {
            href: "#" + s.anchor_id,
            onClick: (ev) => { ev.preventDefault(); onJump(s.anchor_id) }
          },
            e("span", { className: "id" }, s.title.split(" · ")[0]),
            e("span", null, s.title.split(" · ")[1] || ""),
          )
        )
      )
    ),
    e("div", { className: "foot" },
      e("b", null, doc.details_markdown_sections.length), " sections · ",
      SUMMARY_CITES.length, " cited from summary"
    )
  )
}

/* ===================================================================
   Details pane — renders details_markdown_sections
   =================================================================== */
function DetailsPane({ isEditing, activeAnchor, flashAnchor, anchorMode, onPickDetails, detailsPick }) {
  return e("div", { className: "pane details-pane" },
    e("div", { className: "pane-head" },
      e("div", { className: "ttl" }, e("span", { className: "dot" }), e("b", null, "Details"), " · evidence"),
      e("div", { className: "row gap-2" },
        e("span", { className: "kbd" }, doc.details_markdown_sections.length, " sections"),
      )
    ),
    e("div", { className: "pane-body" },
      isEditing && e(Toolbar, { savedAt: "2:14 PM" }),
      e("div", { className: "details-content" },
        doc.details_markdown_sections.map((s) => {
          const brefs = backrefsFor(s.anchor_id)
          return e("section", {
            key: s.anchor_id,
            id: s.anchor_id,
            className: flashAnchor === s.anchor_id ? "flash" : "",
          },
            e("div", { className: "sec-head" },
              e("span", { className: "sec-id" }, s.title.split(" · ")[0]),
              brefs.length > 0 && e("div", { className: "backrefs" },
                "cited from",
                brefs.map((b, i) => e("span", { key: i, className: "br" }, "summary"))
              ),
            ),
            ...renderMarkdown(s.markdown, s.anchor_id)
          )
        })
      )
    )
  )
}

/* ===================================================================
   Resizer for split view
   =================================================================== */
function Resizer({ onDrag }) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    let dragging = false
    function down(ev) { dragging = true; document.body.style.cursor = "col-resize"; ev.preventDefault() }
    function move(ev) { if (!dragging) return; onDrag(ev.clientX) }
    function up()   { dragging = false; document.body.style.cursor = "" }
    el.addEventListener("mousedown", down)
    window.addEventListener("mousemove", move)
    window.addEventListener("mouseup", up)
    return () => {
      el.removeEventListener("mousedown", down)
      window.removeEventListener("mousemove", move)
      window.removeEventListener("mouseup", up)
    }
  }, [onDrag])
  return e("div", { className: "resizer", ref })
}

/* ===================================================================
   Anchor bar (bottom dock) — anchor-creation flow
   =================================================================== */
function AnchorBar({ summaryPick, detailsPick, onConfirm, onCancel, onResetSummary, onResetDetails }) {
  const ready = summaryPick && detailsPick
  return e("div", { className: "anchor-bar" },
    e("div", { className: "kicker" }, e("span", { className: "pulse" }), "anchor mode"),
    e("div", { className: `slot ${summaryPick ? "filled" : ""}`, onClick: onResetSummary, style: { cursor: summaryPick ? "pointer" : "default" } },
      e("span", { className: "lbl" }, "Summary span"),
      summaryPick
        ? e(React.Fragment, null, "“", summaryPick.text.slice(0, 60), summaryPick.text.length > 60 ? "…" : "", "”")
        : "Highlight any text in Summary"
    ),
    e("div", { className: `slot ${detailsPick ? "filled" : ""}`, onClick: onResetDetails, style: { cursor: detailsPick ? "pointer" : "default" } },
      e("span", { className: "lbl" }, "Details span"),
      detailsPick
        ? e(React.Fragment, null, "“", detailsPick.text.slice(0, 60), detailsPick.text.length > 60 ? "…" : "", "”")
        : "Highlight any text in Details"
    ),
    e("div", { className: "actions" },
      e("button", { className: "btn cancel", onClick: onCancel }, "Cancel"),
      e("button", { className: "btn confirm", disabled: !ready, onClick: onConfirm },
        ready ? "Create anchor §" + (SUMMARY_CITES.length + 1) : "Pick both spans"
      ),
    )
  )
}

/* ===================================================================
   Cite drawer (Summary mode — bottom slide-up showing details)
   =================================================================== */
function CiteDrawer({ open, anchorId, onClose, onOpenSplit }) {
  const sec = anchorId ? findSection(anchorId) : null
  return e("div", { className: `cite-drawer ${open ? "open" : ""}` },
    e("div", { className: "head" },
      e("div", { className: "l" },
        sec && e("span", { className: "id" }, sec.title.split(" · ")[0]),
        sec && e("h3", null, (sec.title.split(" · ")[1] || sec.title)),
      ),
      e("div", { className: "actions" },
        e("button", { className: "btn", onClick: onOpenSplit }, "Open in split  ↗"),
        e("button", { className: "btn ghost", onClick: onClose }, "Close"),
      ),
    ),
    e("div", { className: "body" }, sec ? renderMarkdown(sec.markdown, "drawer") : null)
  )
}

/* ===================================================================
   Summary mode side rail (right side metadata, summary-only view)
   =================================================================== */
function MetaRail() {
  return e("aside", { className: "meta-rail" },
    e("div", { className: "blk" },
      e("div", { className: "k" }, "Tokens saved"),
      e("div", { className: "v big num pri" }, fmt(doc.reuse.tokens_saved)),
      e("div", { className: "v" }, "across ", doc.reuse.count, " reuses")
    ),
    e("div", { className: "blk" },
      e("div", { className: "k" }, "Last reuse"),
      e("div", { className: "v" }, "2h ago · @alex"),
      e("div", { className: "v" }, "in ", e("span", { style: { fontFamily: "JetBrains Mono, monospace" } }, "billing.ts"))
    ),
    e("div", { className: "blk" },
      e("div", { className: "k" }, "Anchored sections"),
      e("div", { className: "v" }, SUMMARY_CITES.length, " of ", doc.details_markdown_sections.length, " details sections cited"),
    ),
    e("div", { className: "blk" },
      e("div", { className: "k" }, "Shortcuts"),
      e("div", { className: "v" }, e("span", { className: "kbd" }, "S"), " / ", e("span", { className: "kbd" }, "T"), " / ", e("span", { className: "kbd" }, "D"), "  switch view"),
      e("div", { className: "v" }, e("span", { className: "kbd" }, "E"), "  toggle editor"),
      e("div", { className: "v" }, e("span", { className: "kbd" }, "A"), "  anchor mode (split + edit)"),
    ),
  )
}

/* ===================================================================
   App
   =================================================================== */
function App() {
  const [viewMode, setViewMode] = useState("split")
  const [isEditing, setIsEditing] = useState(false)
  const [anchorMode, setAnchorMode] = useState(false)
  const [summaryPick, setSummaryPick] = useState(null)
  const [detailsPick, setDetailsPick] = useState(null)
  const [activeAnchor, setActiveAnchor] = useState(null)
  const [flashAnchor, setFlashAnchor] = useState(null)
  const [drawerAnchor, setDrawerAnchor] = useState(null)
  const [splitLeft, setSplitLeft] = useState(0.5) // fraction
  const [hoverPoint, setHoverPoint] = useState(null)
  const appRef = useRef(null)
  const hoverTimer = useRef(null)

  // Keyboard shortcuts
  useEffect(() => {
    function onKey(ev) {
      if (ev.target.isContentEditable || /input|textarea/i.test(ev.target.tagName)) return
      if (ev.key === "s" || ev.key === "S") setViewMode("summary")
      else if (ev.key === "t" || ev.key === "T") setViewMode("split")
      else if (ev.key === "d" || ev.key === "D") setViewMode("details")
      else if (ev.key === "e" || ev.key === "E") setIsEditing(v => !v)
      else if ((ev.key === "a" || ev.key === "A") && isEditing && viewMode === "split") setAnchorMode(v => !v)
      else if (ev.key === "Escape") {
        setAnchorMode(false); setDrawerAnchor(null); setSummaryPick(null); setDetailsPick(null)
      }
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [isEditing, viewMode])

  // selection observer — feeds anchor picks when anchorMode is on
  useEffect(() => {
    if (!anchorMode) return
    function onSel() {
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return
      const text = sel.toString().trim()
      if (!text) return
      const range = sel.getRangeAt(0)
      const summaryHost = document.querySelector(".summary-pane .summary-content")
      const detailsHost = document.querySelector(".details-pane .details-content")
      if (summaryHost && summaryHost.contains(range.commonAncestorContainer)) {
        setSummaryPick({ text })
      } else if (detailsHost && detailsHost.contains(range.commonAncestorContainer)) {
        setDetailsPick({ text })
      }
    }
    document.addEventListener("selectionchange", onSel)
    return () => document.removeEventListener("selectionchange", onSel)
  }, [anchorMode])

  // citation click
  const onCiteClick = useCallback((id) => {
    setActiveAnchor(id)
    if (viewMode === "summary") {
      setDrawerAnchor(id)
      return
    }
    // split or details: scroll & flash
    const sec = document.getElementById(id)
    if (sec) sec.scrollIntoView({ block: "start", behavior: "smooth" })
    setFlashAnchor(id)
    setTimeout(() => setFlashAnchor(null), 1700)
  }, [viewMode])

  // hover preview (debounced)
  const onCiteHover = useCallback((id, targetEl) => {
    if (!id) {
      if (hoverTimer.current) { clearTimeout(hoverTimer.current); hoverTimer.current = null }
      setHoverPoint(null)
      return
    }
    if (hoverTimer.current) clearTimeout(hoverTimer.current)
    hoverTimer.current = setTimeout(() => {
      const rect = targetEl.getBoundingClientRect()
      const pane = targetEl.closest(".pane")
      const paneRect = pane ? pane.getBoundingClientRect() : { left: 0, top: 0 }
      // position popover below the chip, relative to .pane-body
      const x = rect.left - paneRect.left
      const y = rect.bottom - paneRect.top + 8
      setHoverPoint({ id, x: Math.min(x, (paneRect.right - paneRect.left) - 340), y })
    }, 280)
  }, [])

  // anchor confirm
  const onConfirm = useCallback(() => {
    // flash both spans + reset state. (Prototype: no real doc mutation.)
    setFlashAnchor(SUMMARY_CITES[0]) // visual stand-in
    setTimeout(() => setFlashAnchor(null), 1700)
    setAnchorMode(false)
    setSummaryPick(null); setDetailsPick(null)
    // tiny toast — could be a state-driven element; keep simple
    showToast(`Anchor created · §${SUMMARY_CITES.length + 1}`)
  }, [])

  // split resizer
  const onResize = useCallback((clientX) => {
    const r = appRef.current?.getBoundingClientRect()
    if (!r) return
    const frac = Math.max(0.22, Math.min(0.78, (clientX - r.left) / r.width))
    setSplitLeft(frac)
  }, [])

  const workspaceStyle = useMemo(() => {
    if (viewMode !== "split") return {}
    const L = (splitLeft * 100).toFixed(2)
    const R = (100 - splitLeft * 100).toFixed(2)
    return { "--split-left": `${L}%`, "--split-right": `${R}%` }
  }, [viewMode, splitLeft])

  return e("div", { className: "app", ref: appRef },
    e(AppBar, null),
    e(DocHeader, {
      viewMode, setViewMode,
      isEditing, setIsEditing,
      anchorMode, setAnchorMode,
    }),

    e("div", { className: `workspace ${viewMode}`, style: workspaceStyle },
      // Summary
      (viewMode === "summary" || viewMode === "split") && e(SummaryPane, {
        isEditing, anchorMode, activeAnchor,
        onCiteClick, onCiteHover, hoverPoint,
        onPickSummary: setSummaryPick, summaryPick,
      }),

      // Resizer (split only)
      viewMode === "split" && e(Resizer, { onDrag: onResize }),

      // Outline (details only)
      viewMode === "details" && e(Outline, {
        activeAnchor, onJump: (id) => {
          const el = document.getElementById(id)
          if (el) el.scrollIntoView({ block: "start", behavior: "smooth" })
          setActiveAnchor(id); setFlashAnchor(id)
          setTimeout(() => setFlashAnchor(null), 1700)
        }
      }),

      // Details
      (viewMode === "details" || viewMode === "split") && e(DetailsPane, {
        isEditing, activeAnchor, flashAnchor, anchorMode,
        onPickDetails: setDetailsPick, detailsPick,
      }),

      // Right meta rail (summary-only)
      viewMode === "summary" && e(MetaRail, null),

      // Drawer (Summary mode preview)
      viewMode === "summary" && e(CiteDrawer, {
        open: !!drawerAnchor,
        anchorId: drawerAnchor,
        onClose: () => setDrawerAnchor(null),
        onOpenSplit: () => {
          const id = drawerAnchor
          setDrawerAnchor(null)
          setViewMode("split")
          setTimeout(() => {
            const sec = document.getElementById(id)
            if (sec) sec.scrollIntoView({ block: "start", behavior: "smooth" })
            setFlashAnchor(id); setTimeout(() => setFlashAnchor(null), 1700)
          }, 80)
        }
      }),
    ),

    // Anchor bar (floating)
    anchorMode && e(AnchorBar, {
      summaryPick, detailsPick,
      onConfirm,
      onCancel: () => { setAnchorMode(false); setSummaryPick(null); setDetailsPick(null) },
      onResetSummary: () => setSummaryPick(null),
      onResetDetails: () => setDetailsPick(null),
    }),
  )
}

// minimal toast
function showToast(text) {
  const t = document.createElement("div")
  t.textContent = text
  Object.assign(t.style, {
    position: "fixed", bottom: "24px", right: "24px",
    background: "var(--ink)", color: "white",
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: "11px", letterSpacing: "0.06em",
    padding: "10px 14px", border: "1px solid var(--ink)",
    zIndex: 9999, boxShadow: "0 8px 24px -8px rgba(0,0,0,0.3)",
  })
  document.body.appendChild(t)
  setTimeout(() => { t.style.opacity = "0"; t.style.transition = "opacity 200ms ease" }, 1600)
  setTimeout(() => t.remove(), 2000)
}

const root = ReactDOM.createRoot(document.getElementById("root"))
document.getElementById("root").classList.remove("boot")
root.render(e(App, null))
