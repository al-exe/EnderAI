/* global React */
// Minimal markdown renderer for the prototype.
// Handles: h2/h3, paragraphs, ordered/unordered lists, code blocks,
// inline code, bold (**…**), italic (*…* / _…_), simple tables.
// Returns React elements.

(function (global) {
  const { createElement: h } = React

  function inline(text, keyPrefix = "i") {
    // Tokenize: `code`, **bold**, *italic*
    const tokens = []
    let i = 0
    while (i < text.length) {
      if (text[i] === "`") {
        const end = text.indexOf("`", i + 1)
        if (end > -1) {
          tokens.push(h("code", { key: `${keyPrefix}-${i}` }, text.slice(i + 1, end)))
          i = end + 1
          continue
        }
      }
      if (text[i] === "*" && text[i + 1] === "*") {
        const end = text.indexOf("**", i + 2)
        if (end > -1) {
          tokens.push(h("strong", { key: `${keyPrefix}-${i}` }, text.slice(i + 2, end)))
          i = end + 2
          continue
        }
      }
      if (text[i] === "*") {
        const end = text.indexOf("*", i + 1)
        if (end > -1) {
          tokens.push(h("em", { key: `${keyPrefix}-${i}` }, text.slice(i + 1, end)))
          i = end + 1
          continue
        }
      }
      // accumulate plain
      let j = i
      while (j < text.length && text[j] !== "`" && text[j] !== "*") j++
      if (j > i) tokens.push(text.slice(i, j))
      i = j
    }
    return tokens
  }

  function renderTable(rows, keyPrefix) {
    const head = rows[0]
    const body = rows.slice(2)
    return h("table", { key: keyPrefix },
      h("thead", null,
        h("tr", null, head.map((c, i) => h("th", { key: i }, inline(c, `th-${i}`))))
      ),
      h("tbody", null,
        body.map((r, ri) =>
          h("tr", { key: ri }, r.map((c, ci) => h("td", { key: ci }, inline(c, `td-${ri}-${ci}`))))
        )
      )
    )
  }

  function parseRow(line) {
    // strip leading/trailing `|`
    let s = line.trim()
    if (s.startsWith("|")) s = s.slice(1)
    if (s.endsWith("|")) s = s.slice(0, -1)
    return s.split("|").map((c) => c.trim())
  }

  global.renderMarkdown = function renderMarkdown(md, keyPrefix = "md") {
    const lines = md.split("\n")
    const out = []
    let i = 0
    while (i < lines.length) {
      const ln = lines[i]

      // code block
      if (ln.trim().startsWith("```")) {
        const buf = []
        i++
        while (i < lines.length && !lines[i].trim().startsWith("```")) { buf.push(lines[i]); i++ }
        i++
        out.push(h("pre", { key: `${keyPrefix}-pre-${i}` }, h("code", null, buf.join("\n"))))
        continue
      }

      // table
      if (ln.trim().startsWith("|")) {
        const buf = []
        while (i < lines.length && lines[i].trim().startsWith("|")) {
          buf.push(parseRow(lines[i]))
          i++
        }
        out.push(renderTable(buf, `${keyPrefix}-tbl-${i}`))
        continue
      }

      // heading
      if (ln.startsWith("### ")) { out.push(h("h3", { key: `${keyPrefix}-h3-${i}` }, inline(ln.slice(4), `h3-${i}`))); i++; continue }
      if (ln.startsWith("## "))  { out.push(h("h2", { key: `${keyPrefix}-h2-${i}` }, inline(ln.slice(3), `h2-${i}`))); i++; continue }
      if (ln.startsWith("# "))   { out.push(h("h2", { key: `${keyPrefix}-h1-${i}` }, inline(ln.slice(2), `h1-${i}`))); i++; continue }

      // unordered list
      if (/^[-*]\s/.test(ln)) {
        const items = []
        while (i < lines.length && /^[-*]\s/.test(lines[i])) {
          items.push(lines[i].replace(/^[-*]\s/, ""))
          i++
        }
        out.push(h("ul", { key: `${keyPrefix}-ul-${i}` }, items.map((t, j) => h("li", { key: j }, inline(t, `li-${j}`)))))
        continue
      }
      // ordered list
      if (/^\d+\.\s/.test(ln)) {
        const items = []
        while (i < lines.length && /^\d+\.\s/.test(lines[i])) {
          items.push(lines[i].replace(/^\d+\.\s/, ""))
          i++
        }
        out.push(h("ol", { key: `${keyPrefix}-ol-${i}` }, items.map((t, j) => h("li", { key: j }, inline(t, `oli-${j}`)))))
        continue
      }

      // blank line
      if (!ln.trim()) { i++; continue }

      // paragraph — gather consecutive non-blank lines
      const buf = [ln]
      i++
      while (i < lines.length && lines[i].trim() && !/^[-*#>]|^\d+\./.test(lines[i]) && !lines[i].startsWith("```") && !lines[i].startsWith("|")) {
        buf.push(lines[i])
        i++
      }
      out.push(h("p", { key: `${keyPrefix}-p-${i}` }, inline(buf.join(" "), `pi-${i}`)))
    }
    return out
  }
})(window)
