CREATE TABLE IF NOT EXISTS item(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('rule','task','knowledge','draft','note','step','gate')),
  title TEXT NOT NULL, body TEXT,
  status TEXT NOT NULL CHECK(status IN ('proposed','approved','open','doing','review','done','rejected')),
  priority TEXT, spec JSON CHECK(spec IS NULL OR json_valid(spec)), always_load INT NOT NULL DEFAULT 0, core INT NOT NULL DEFAULT 0,
  owner TEXT, claimed_at TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, version INT NOT NULL DEFAULT 1,
  phase INT, roadmap TEXT, label TEXT);

-- roadmap steps/gates are addressed by (roadmap, step_key)
CREATE UNIQUE INDEX IF NOT EXISTS item_step_key ON item(project, json_extract(spec,'$.roadmap'), json_extract(spec,'$.step_key')) WHERE kind IN ('step','gate');

CREATE TABLE IF NOT EXISTS item_dep(
  item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  depends_on INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  PRIMARY KEY(item_id,depends_on), CHECK(item_id<>depends_on));

CREATE TABLE IF NOT EXISTS c4_object(
  id TEXT NOT NULL, project TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('actor','system','app','store','component','group','file','function')),
  name TEXT NOT NULL, parent TEXT, technology TEXT, description TEXT, kind TEXT,
  tags JSON, links JSON, status TEXT, responsibilities JSON, state TEXT, owns JSON, behavior TEXT, PRIMARY KEY(project,id));
CREATE TABLE IF NOT EXISTS c4_connection(
  id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
  name TEXT, status TEXT, description TEXT, detail TEXT, PRIMARY KEY(project,id));
CREATE TABLE IF NOT EXISTS c4_meta(
  project TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT, layout TEXT, tags JSON, positions JSON, source TEXT);
CREATE TABLE IF NOT EXISTS c4_flow(
  id TEXT NOT NULL, project TEXT NOT NULL, name TEXT, steps JSON, PRIMARY KEY(project,id));

-- layered C4 folder (c4_layered.py): call detail per link, behavior per module
CREATE TABLE IF NOT EXISTS c4_contract(
  project TEXT NOT NULL, id TEXT NOT NULL, transport TEXT, body JSON, start JSON, end_sym TEXT, PRIMARY KEY(project,id));
CREATE TABLE IF NOT EXISTS c4_behavior(
  project TEXT NOT NULL, module TEXT NOT NULL, form TEXT, data JSON, PRIMARY KEY(project,module));

CREATE TABLE IF NOT EXISTS audit(
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  project TEXT, actor_role TEXT, tool TEXT, target TEXT, before JSON, after JSON);

-- đ/Đ do not decompose, so triggers fold them to d/D; fold queries too (db.fold)
CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(
  title, body, src UNINDEXED, ref UNINDEXED, project UNINDEXED,
  tokenize='unicode61 remove_diacritics 2');

CREATE TRIGGER IF NOT EXISTS item_ai AFTER INSERT ON item BEGIN
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),replace(replace(NEW.body,'đ','d'),'Đ','D'),'item',NEW.id,NEW.project); END;
CREATE TRIGGER IF NOT EXISTS item_au AFTER UPDATE ON item BEGIN
  DELETE FROM search WHERE src='item' AND ref=OLD.id;
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),replace(replace(NEW.body,'đ','d'),'Đ','D'),'item',NEW.id,NEW.project); END;
CREATE TRIGGER IF NOT EXISTS item_ad AFTER DELETE ON item BEGIN
  DELETE FROM search WHERE src='item' AND ref=OLD.id; END;

CREATE TABLE IF NOT EXISTS page(
  project TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('research','note','plan')),
  blocks JSON NOT NULL CHECK(json_valid(blocks)), text TEXT, updated_at TEXT,
  PRIMARY KEY(project,slug));

CREATE TRIGGER IF NOT EXISTS page_ai AFTER INSERT ON page BEGIN
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),replace(replace(NEW.text,'đ','d'),'Đ','D'),'page',NEW.rowid,NEW.project); END;
CREATE TRIGGER IF NOT EXISTS page_au AFTER UPDATE ON page BEGIN
  DELETE FROM search WHERE src='page' AND ref=OLD.rowid;
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),replace(replace(NEW.text,'đ','d'),'Đ','D'),'page',NEW.rowid,NEW.project); END;
CREATE TRIGGER IF NOT EXISTS page_ad AFTER DELETE ON page BEGIN
  DELETE FROM search WHERE src='page' AND ref=OLD.rowid; END;

-- research became page kind=research (db.init refuses to drop a non-empty table)
DROP TABLE IF EXISTS research;
DELETE FROM search WHERE src='research';

CREATE TABLE IF NOT EXISTS project(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT, root TEXT, docs_dir TEXT,
  parent TEXT REFERENCES project(id), status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));

CREATE TABLE IF NOT EXISTS doc(
  project TEXT NOT NULL, path TEXT NOT NULL, title TEXT NOT NULL, feature TEXT,
  kind TEXT NOT NULL DEFAULT 'other' CHECK(kind IN ('research','architect','review','plan','other')),
  status TEXT NOT NULL DEFAULT 'current' CHECK(status IN ('current','draft','outdated','missing')),
  ord INT NOT NULL DEFAULT 0, text TEXT, updated_at TEXT, summary TEXT, code JSON, prev_status TEXT,
  PRIMARY KEY(project,path));

CREATE TRIGGER IF NOT EXISTS doc_ai AFTER INSERT ON doc BEGIN
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),replace(replace(NEW.text,'đ','d'),'Đ','D'),'doc',NEW.rowid,NEW.project); END;
CREATE TRIGGER IF NOT EXISTS doc_au AFTER UPDATE ON doc BEGIN
  DELETE FROM search WHERE src='doc' AND ref=OLD.rowid;
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),replace(replace(NEW.text,'đ','d'),'Đ','D'),'doc',NEW.rowid,NEW.project); END;
CREATE TRIGGER IF NOT EXISTS doc_ad AFTER DELETE ON doc BEGIN
  DELETE FROM search WHERE src='doc' AND ref=OLD.rowid; END;

-- links an object to a task/issue; no FK (objects are re-imported)
CREATE TABLE IF NOT EXISTS c4_link(
  project TEXT NOT NULL, object_id TEXT NOT NULL,
  ref_kind TEXT NOT NULL CHECK(ref_kind IN ('item')), ref_id INTEGER NOT NULL,
  PRIMARY KEY(project,object_id,ref_kind,ref_id));
