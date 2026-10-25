// Detail panel. Text only via textContent: node names/files come from the repo.
const $ = (id) => document.getElementById(id);

export function createPanel({ onPick }) {
  const f = { kicker: $('detail-kicker'), title: $('detail-title'), kind: $('detail-kind'), degree: $('detail-degree'),
    community: $('detail-community'), file: $('detail-file'), note: $('detail-note'), list: $('neighbours'), label: $('neighbours-label') };
  const dash = (...els) => els.forEach((e) => { e.textContent = '—'; });
  const clearList = () => { f.list.replaceChildren(); f.label.hidden = true; };

  function message(kicker, title, note) {
    f.kicker.textContent = kicker; f.title.textContent = title; f.note.textContent = note;
    dash(f.kind, f.degree, f.community, f.file); clearList();
  }
  // node: adapt() node; neighbours: [{index, name, degree}]
  function showNode(node, neighbours, pinned) {
    f.kicker.textContent = pinned ? 'Selected object' : 'Object in focus';
    f.title.textContent = node.name;
    f.kind.textContent = node.kind;
    f.degree.textContent = String(node.degree);
    f.community.textContent = node.community ?? '—';
    f.file.textContent = node.file ?? '—';
    f.note.textContent = pinned ? 'Pinned. Escape clears.' : 'Click to pin.';
    f.label.hidden = neighbours.length === 0;
    f.list.replaceChildren(...neighbours.map((n) => {
      const li = document.createElement('li'), b = document.createElement('button'), d = document.createElement('span');
      b.type = 'button'; b.textContent = n.name; d.textContent = String(n.degree);
      b.append(d); b.addEventListener('click', () => onPick(n.index));
      li.append(b); return li;
    }));
  }
  return { message, showNode };
}
