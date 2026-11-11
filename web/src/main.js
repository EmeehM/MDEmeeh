// Emeeh Markdown — editor WYSIWYG estilo Typora
import { Editor, Extension } from '@tiptap/core'
import { TextSelection } from '@tiptap/pm/state'
import StarterKit from '@tiptap/starter-kit'
import { TableKit } from '@tiptap/extension-table'
import { TaskList, TaskItem } from '@tiptap/extension-list'
import { Placeholder } from '@tiptap/extensions'
import Image from '@tiptap/extension-image'
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight'
import { createLowlight, common } from 'lowlight'
import { Markdown } from 'tiptap-markdown'

const $ = (sel) => document.querySelector(sel)

// ---------------------------------------------------------------------------
// Puente con Python (QWebChannel). Si no existe (abierto en navegador) usa un stub.
// ---------------------------------------------------------------------------
let bridge = {
  setDirty() {},
  openUrl(url) { window.open(url, '_blank') },
  ready() {},
}

function initBridge(cb) {
  if (window.qt && window.QWebChannel) {
    new window.QWebChannel(window.qt.webChannelTransport, (channel) => {
      bridge = channel.objects.bridge
      cb()
    })
  } else {
    cb()
  }
}

// ---------------------------------------------------------------------------
// Extensión: "| col1 | col2 |" + Enter  →  tabla (como en Typora)
// ---------------------------------------------------------------------------
const TableFromPipes = Extension.create({
  name: 'tableFromPipes',
  addKeyboardShortcuts() {
    return {
      'Mod-Shift-x': ({ editor }) => editor.commands.toggleStrike(),
      Enter: ({ editor }) => {
        const { state } = editor
        const { $from, empty } = state.selection
        if (!empty || $from.parent.type.name !== 'paragraph') return false
        if (editor.isActive('table') || editor.isActive('codeBlock')) return false
        const text = $from.parent.textContent
        const m = text.match(/^\s*\|(.+)\|\s*$/)
        if (!m) return false
        const cells = m[1].split('|').map((c) => c.trim())
        if (cells.length < 1) return false

        const cell = (type, txt) => ({
          type,
          content: [{ type: 'paragraph', content: txt ? [{ type: 'text', text: txt }] : [] }],
        })
        const json = {
          type: 'table',
          content: [
            { type: 'tableRow', content: cells.map((c) => cell('tableHeader', c)) },
            { type: 'tableRow', content: cells.map(() => cell('tableCell', '')) },
          ],
        }
        const tableNode = state.schema.nodeFromJSON(json)
        const from = $from.before()
        const to = $from.after()
        const tr = state.tr.replaceWith(from, to, tableNode)
        // Cursor en la primera celda de la primera fila del cuerpo
        const headerRow = tableNode.child(0)
        const pos = from + 1 + headerRow.nodeSize + 1 + 1 + 1
        tr.setSelection(TextSelection.create(tr.doc, pos))
        editor.view.dispatch(tr.scrollIntoView())
        return true
      },
    }
  },
})

// Las listas de tareas también se guardan "compactas" (sin línea en blanco entre ítems)
const TightTaskLists = Extension.create({
  name: 'tightTaskLists',
  addGlobalAttributes() {
    return [{
      types: ['taskList'],
      attributes: {
        tight: {
          default: true,
          parseHTML: (el) => el.getAttribute('data-tight') === 'true' || !el.querySelector('p'),
          renderHTML: (attrs) => (attrs.tight ? { 'data-tight': 'true' } : {}),
        },
      },
    }]
  },
})

// ---------------------------------------------------------------------------
// Editor
// ---------------------------------------------------------------------------
const lowlight = createLowlight(common)

let dirty = false
let sourceMode = false
let suppressDirty = false

const editor = new Editor({
  element: $('#editor'),
  autofocus: 'start',
  extensions: [
    StarterKit.configure({
      codeBlock: false,
      link: { openOnClick: false, autolink: true, linkOnPaste: true },
      heading: { levels: [1, 2, 3, 4, 5, 6] },
    }),
    CodeBlockLowlight.configure({ lowlight, defaultLanguage: null }),
    TableKit.configure({ table: { resizable: false } }),
    TaskList,
    TaskItem.configure({ nested: true }),
    Image.configure({ inline: false, allowBase64: true }),
    Placeholder.configure({
      placeholder: ({ node }) =>
        node.type.name === 'heading' ? `Título ${node.attrs.level}` : 'Empieza a escribir…  (# Título, **negrita**, | a | b | + Enter para tabla)',
    }),
    Markdown.configure({
      html: true,
      tightLists: true,
      bulletListMarker: '-',
      linkify: true,
      breaks: false,
      transformPastedText: true,
      transformCopiedText: false,
    }),
    TableFromPipes,
    TightTaskLists,
  ],
  onUpdate: () => {
    if (!suppressDirty) markDirty()
    scheduleSideUpdates()
  },
  onSelectionUpdate: () => updateTableToolbar(),
})

function markDirty() {
  if (!dirty) {
    dirty = true
    bridge.setDirty(true)
  }
}

// ---------------------------------------------------------------------------
// Modo código fuente
// ---------------------------------------------------------------------------
const sourceEl = $('#source')

function setSourceMode(on) {
  if (on === sourceMode) return
  if (on) {
    sourceEl.value = getMarkdown()
    sourceMode = true
    document.body.classList.add('source-mode')
    sourceEl.focus()
    sourceEl.setSelectionRange(0, 0)
    sourceEl.scrollTop = 0
  } else {
    const md = sourceEl.value
    sourceMode = false
    document.body.classList.remove('source-mode')
    suppressDirty = true
    editor.commands.setContent(md, { emitUpdate: true })
    suppressDirty = false
    editor.commands.focus('start')
  }
  hideTableToolbar()
  scheduleSideUpdates()
}

sourceEl.addEventListener('input', () => {
  markDirty()
  scheduleSideUpdates()
})
sourceEl.addEventListener('keydown', (e) => {
  if (e.key === 'Tab') {
    e.preventDefault()
    const s = sourceEl.selectionStart
    const en = sourceEl.selectionEnd
    sourceEl.setRangeText('    ', s, en, 'end')
    markDirty()
  }
})

function getMarkdown() {
  if (sourceMode) return sourceEl.value
  return editor.storage.markdown.getMarkdown()
}

// ---------------------------------------------------------------------------
// Barra de herramientas de tabla (flotante)
// ---------------------------------------------------------------------------
const tableBar = $('#table-toolbar')
const scroller = $('#scroller')

function hideTableToolbar() {
  tableBar.hidden = true
}

function updateTableToolbar() {
  if (sourceMode || !editor.isActive('table')) return hideTableToolbar()
  const { node } = editor.view.domAtPos(editor.state.selection.from)
  const el = node.nodeType === 1 ? node : node.parentElement
  const table = el && el.closest('table')
  if (!table) return hideTableToolbar()
  const tRect = table.getBoundingClientRect()
  const sRect = scroller.getBoundingClientRect()
  tableBar.hidden = false
  const top = tRect.top - sRect.top + scroller.scrollTop - tableBar.offsetHeight - 6
  tableBar.style.top = `${Math.max(top, scroller.scrollTop)}px`
  tableBar.style.left = `${tRect.left - sRect.left + scroller.scrollLeft}px`
}

tableBar.addEventListener('mousedown', (e) => e.preventDefault())
tableBar.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-t]')
  if (!btn) return
  const c = editor.chain().focus()
  const actions = {
    rowBefore: () => c.addRowBefore(),
    rowAfter: () => c.addRowAfter(),
    colBefore: () => c.addColumnBefore(),
    colAfter: () => c.addColumnAfter(),
    delRow: () => c.deleteRow(),
    delCol: () => c.deleteColumn(),
    header: () => c.toggleHeaderRow(),
    delTable: () => c.deleteTable(),
  }
  actions[btn.dataset.t]?.().run()
  updateTableToolbar()
})
scroller.addEventListener('scroll', () => {
  if (!tableBar.hidden) updateTableToolbar()
})
window.addEventListener('resize', () => updateTableToolbar())

// ---------------------------------------------------------------------------
// Esquema (outline) y contador de palabras
// ---------------------------------------------------------------------------
const outlineEl = $('#outline-list')
const statusEl = $('#status')
let sideTimer = null
let flashTimer = null

function scheduleSideUpdates() {
  clearTimeout(sideTimer)
  sideTimer = setTimeout(() => {
    updateOutline()
    updateStatus()
    updateTableToolbar()
  }, 150)
}

function updateOutline() {
  if (document.body.classList.contains('hide-outline')) return
  const items = []
  if (sourceMode) {
    let inFence = false
    sourceEl.value.split('\n').forEach((line, i) => {
      if (/^\s*(```|~~~)/.test(line)) inFence = !inFence
      const m = !inFence && line.match(/^(#{1,6})\s+(.*)$/)
      if (m) items.push({ level: m[1].length, text: m[2].replace(/#+\s*$/, ''), line: i })
    })
  } else {
    editor.state.doc.descendants((node, pos) => {
      if (node.type.name === 'heading') items.push({ level: node.attrs.level, text: node.textContent, pos })
      return node.type.name !== 'table'
    })
  }
  outlineEl.innerHTML = ''
  if (!items.length) {
    outlineEl.innerHTML = '<li class="empty">Sin títulos</li>'
    return
  }
  for (const it of items) {
    const li = document.createElement('li')
    li.className = `lvl-${it.level}`
    li.textContent = it.text || '(sin título)'
    li.title = it.text
    li.addEventListener('click', () => {
      if (sourceMode) {
        const lines = sourceEl.value.split('\n')
        const offset = lines.slice(0, it.line).reduce((a, l) => a + l.length + 1, 0)
        sourceEl.focus()
        sourceEl.setSelectionRange(offset, offset)
        const lh = parseFloat(getComputedStyle(sourceEl).lineHeight) || 22
        sourceEl.scrollTop = Math.max(0, it.line * lh - 40)
      } else {
        editor.chain().focus().setTextSelection(it.pos + 1).run()
        const dom = editor.view.nodeDOM(it.pos)
        if (dom && dom.scrollIntoView) dom.scrollIntoView({ block: 'start', behavior: 'smooth' })
      }
    })
    outlineEl.appendChild(li)
  }
}

function updateStatus() {
  if (statusEl.classList.contains('flash')) return
  const text = sourceMode ? sourceEl.value : editor.state.doc.textBetween(0, editor.state.doc.content.size, '\n', ' ')
  const words = (text.match(/[\p{L}\p{N}_'’-]+/gu) || []).length
  const chars = text.replace(/\n/g, '').length
  statusEl.textContent = `${words.toLocaleString('es')} palabras · ${chars.toLocaleString('es')} caracteres${sourceMode ? ' · Código fuente' : ''}`
}

// ---------------------------------------------------------------------------
// Barra de formato (opcional)
// ---------------------------------------------------------------------------
const toolbar = $('#toolbar')
toolbar.addEventListener('mousedown', (e) => {
  if (e.target.closest('button')) e.preventDefault()
})
toolbar.addEventListener('click', (e) => {
  const btn = e.target.closest('button[data-cmd]')
  if (btn) app.command(btn.dataset.cmd)
})

function refreshToolbarState() {
  toolbar.querySelectorAll('button[data-cmd]').forEach((b) => {
    const map = {
      h1: ['heading', { level: 1 }], h2: ['heading', { level: 2 }], h3: ['heading', { level: 3 }],
      bold: ['bold'], italic: ['italic'], strike: ['strike'], code: ['code'],
      ul: ['bulletList'], ol: ['orderedList'], task: ['taskList'], quote: ['blockquote'],
      codeblock: ['codeBlock'], link: ['link'],
    }
    const m = map[b.dataset.cmd]
    b.classList.toggle('active', !!m && !sourceMode && editor.isActive(...m))
  })
}
editor.on('selectionUpdate', refreshToolbarState)
editor.on('transaction', refreshToolbarState)

// ---------------------------------------------------------------------------
// Enlaces: Ctrl+clic abre en el navegador
// ---------------------------------------------------------------------------
$('#editor').addEventListener('click', (e) => {
  const a = e.target.closest('a[href]')
  if (a && (e.ctrlKey || e.metaKey)) {
    e.preventDefault()
    bridge.openUrl(a.getAttribute('href'))
  }
})
$('#editor').addEventListener('mousemove', (e) => {
  document.body.classList.toggle('ctrl-held', e.ctrlKey || e.metaKey)
})

// ---------------------------------------------------------------------------
// API pública usada desde Python
// ---------------------------------------------------------------------------
const app = {
  setContent(md, baseUrl) {
    if (baseUrl) $('base').setAttribute('href', baseUrl)
    suppressDirty = true
    if (sourceMode) sourceEl.value = md
    editor.commands.setContent(md || '', { emitUpdate: false })
    suppressDirty = false
    dirty = false
    editor.commands.focus('start')
    editor.view.dom.scrollTop = 0
    scroller.scrollTop = 0
    scheduleSideUpdates()
  },
  setBase(baseUrl) {
    $('base').setAttribute('href', baseUrl)
  },
  getMarkdown,
  markSaved() {
    dirty = false
  },
  isDirty: () => dirty,
  getHtml() {
    if (sourceMode) {
      suppressDirty = true
      editor.commands.setContent(sourceEl.value, { emitUpdate: false })
      suppressDirty = false
    }
    return editor.getHTML()
  },
  setTheme(theme) {
    document.documentElement.dataset.theme = theme
  },
  toggleSource() {
    setSourceMode(!sourceMode)
    return sourceMode
  },
  toggleOutline(show) {
    document.body.classList.toggle('hide-outline', !show)
    scheduleSideUpdates()
  },
  toggleToolbar(show) {
    document.body.classList.toggle('hide-toolbar', !show)
  },
  setFocusWidth(wide) {
    document.body.classList.toggle('wide', !!wide)
  },
  insertImage(src, alt) {
    if (sourceMode) {
      sourceEl.setRangeText(`![${alt || ''}](${src})`, sourceEl.selectionStart, sourceEl.selectionEnd, 'end')
      markDirty()
      return
    }
    editor.chain().focus().setImage({ src, alt: alt || '' }).run()
  },
  command(cmd, arg) {
    if (sourceMode) {
      if (cmd === 'source') setSourceMode(false)
      return
    }
    const c = editor.chain().focus()
    const run = {
      paragraph: () => c.setParagraph(),
      h1: () => c.toggleHeading({ level: 1 }),
      h2: () => c.toggleHeading({ level: 2 }),
      h3: () => c.toggleHeading({ level: 3 }),
      h4: () => c.toggleHeading({ level: 4 }),
      h5: () => c.toggleHeading({ level: 5 }),
      h6: () => c.toggleHeading({ level: 6 }),
      bold: () => c.toggleBold(),
      italic: () => c.toggleItalic(),
      underline: () => c.toggleUnderline(),
      strike: () => c.toggleStrike(),
      code: () => c.toggleCode(),
      codeblock: () => c.toggleCodeBlock(),
      quote: () => c.toggleBlockquote(),
      ul: () => c.toggleBulletList(),
      ol: () => c.toggleOrderedList(),
      task: () => c.toggleTaskList(),
      hr: () => c.setHorizontalRule(),
      table: () => {
        const [rows, cols] = (arg || '3x3').split('x').map(Number)
        return c.insertTable({ rows: rows || 3, cols: cols || 3, withHeaderRow: true })
      },
      link: () => {
        if (editor.isActive('link')) return c.unsetLink()
        const href = arg || window.__pendingLink
        if (!href) return c
        return c.extendMarkRange('link').setLink({ href })
      },
      clear: () => c.unsetAllMarks().clearNodes(),
      undo: () => c.undo(),
      redo: () => c.redo(),
      source: () => {
        setSourceMode(true)
        return null
      },
    }[cmd]
    if (!run) return
    if (cmd === 'link' && !editor.isActive('link') && !arg) {
      openLinkPrompt()
      return
    }
    const chain = run()
    if (chain) chain.run()
  },
  flash(msg) {
    statusEl.textContent = msg
    statusEl.classList.add('flash')
    clearTimeout(flashTimer)
    flashTimer = setTimeout(() => {
      statusEl.classList.remove('flash')
      updateStatus()
    }, 3000)
  },
  selectedText() {
    const { from, to } = editor.state.selection
    return editor.state.doc.textBetween(from, to, ' ')
  },
}
window.app = app

// ---------------------------------------------------------------------------
// Diálogo para enlaces
// ---------------------------------------------------------------------------
const linkDlg = $('#link-dialog')
const linkInput = $('#link-input')
let savedSel = null

function openLinkPrompt() {
  savedSel = editor.state.selection
  linkDlg.hidden = false
  linkInput.value = ''
  linkInput.focus()
}
function closeLinkPrompt(apply) {
  linkDlg.hidden = true
  const href = linkInput.value.trim()
  const chain = editor.chain().focus()
  if (savedSel) chain.setTextSelection({ from: savedSel.from, to: savedSel.to })
  if (apply && href) {
    if (savedSel && savedSel.empty) {
      chain.insertContent({ type: 'text', text: href, marks: [{ type: 'link', attrs: { href } }] })
    } else {
      chain.extendMarkRange('link').setLink({ href })
    }
  }
  chain.run()
}
linkInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); closeLinkPrompt(true) }
  if (e.key === 'Escape') { e.preventDefault(); closeLinkPrompt(false) }
})
$('#link-ok').addEventListener('click', () => closeLinkPrompt(true))
$('#link-cancel').addEventListener('click', () => closeLinkPrompt(false))

// ---------------------------------------------------------------------------
initBridge(() => {
  scheduleSideUpdates()
  bridge.ready()
})
