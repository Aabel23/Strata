// Detail panel. Text only via textContent: node names/files come from the repo.
const $ = (id) => document.getElementById(id);

export function createPanel({ onPick, onClose }) {
  const box = $('detail');
  $('detail-close').addEventListener('click', () => onClose());
  const f = { kicker: $('detail-kicker'), title: $('detail-title'), kind: $('detail-kind'), degree: $('detail-degree'),
    community: $('detail-community'), file: $('detail-file'), note: $('detail-note'), list: $('neighbours'), label: $('neighbours-label') };
  const dash = (...els) => els.forEach((e) => { e.textContent = '—'; });
  const clearList = () => { f.list.replaceChildren(); f.label.hidden = true; };

  function message(kicker, title, note) { // loading / error notice, pinned top-left
    box.hidden = false; box.classList.add('notice'); box.style.left = box.style.top = '';
    f.kicker.textContent = kicker; f.title.textContent = title; f.note.textContent = note;
    dash(f.kind, f.degree, f.community, f.file); clearList();
  }
  // node: adapt() node; neighbours: [{index, name, degree}]
  function showNode(node, neighbours) {
    box.hidden = false; box.classList.remove('notice');
    f.kicker.textContent = 'Selected object';
    f.title.textContent = node.name;
    f.kind.textContent = node.kind;
    f.degree.textContent = String(node.degree);
    f.community.textContent = node.community ?? '—';
    f.file.textContent = node.file ?? '—';
    f.note.textContent = '';
    f.label.hidden = neighbours.length === 0;
    f.list.replaceChildren(...neighbours.map((n) => {
      const li = document.createElement('li'), b = document.createElement('button'), d = document.createElement('span');
      b.type = 'button'; b.textContent = n.name; d.textContent = String(n.degree);
      b.append(d); b.addEventListener('click', () => onPick(n.index));
      li.append(b); return li;
    }));
  }
  const hide = () => { box.hidden = true; };
  // put the card beside screen point (sx, sy) inside a W x H viewport, flipping near the edges
  function place(sx, sy, W, H) {
    const w = box.offsetWidth, h = box.offsetHeight, m = 8, gap = 16;
    const left = sx + gap + w + m <= W ? sx + gap : Math.max(m, sx - gap - w);
    box.style.left = left + 'px'; box.style.top = Math.max(m, Math.min(H - h - m, sy - 20)) + 'px';
  }
  return { message, showNode, hide, place };
}
