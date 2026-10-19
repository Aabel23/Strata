CREATE TABLE IF NOT EXISTS item(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('rule','task','issue','knowledge','draft','note','step','gate')),
  title TEXT NOT NULL, body TEXT,
  status TEXT NOT NULL CHECK(status IN ('proposed','approved','open','doing','review','done','rejected')),
  priority TEXT, spec JSON CHECK(spec IS NULL OR json_valid(spec)), always_load INT NOT NULL DEFAULT 0, core INT NOT NULL DEFAULT 0,
  owner TEXT, claimed_at TEXT, created_by TEXT, created_at TEXT, updated_at TEXT, version INT NOT NULL DEFAULT 1);

-- roadmap steps/gates are addressed by (roadmap, step_key)
CREATE UNIQUE INDEX IF NOT EXISTS item_step_key ON item(project, json_extract(spec,'$.roadmap'), json_extract(spec,'$.step_key')) WHERE kind IN ('step','gate');

CREATE TABLE IF NOT EXISTS item_dep(
  item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  depends_on INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  PRIMARY KEY(item_id,depends_on), CHECK(item_id<>depends_on));

CREATE TABLE IF NOT EXISTS decision(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('proposed','accepted','superseded')),
  context TEXT, decision TEXT, consequences TEXT,
  rejected_options TEXT NOT NULL CHECK(trim(rejected_options) NOT IN ('','[]')),
  supersedes INTEGER REFERENCES decision(id), created_at TEXT);

CREATE TRIGGER IF NOT EXISTS decision_no_replace BEFORE INSERT ON decision WHEN EXISTS(SELECT 1 FROM decision WHERE id=NEW.id)
BEGIN SELECT RAISE(ABORT,'decision is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_no_delete BEFORE DELETE ON decision
BEGIN SELECT RAISE(ABORT,'decision is append-only'); END;
CREATE TRIGGER IF NOT EXISTS decision_status_only BEFORE UPDATE ON decision
WHEN NEW.id IS NOT OLD.id OR NEW.project IS NOT OLD.project OR NEW.title IS NOT OLD.title
  OR NEW.context IS NOT OLD.context OR NEW.decision IS NOT OLD.decision
  OR NEW.consequences IS NOT OLD.consequences OR NEW.rejected_options IS NOT OLD.rejected_options
  OR NEW.supersedes IS NOT OLD.supersedes OR NEW.created_at IS NOT OLD.created_at
BEGIN SELECT RAISE(ABORT,'decision: only status may change'); END;

CREATE TABLE IF NOT EXISTS c4_object(
  id TEXT NOT NULL, project TEXT NOT NULL,
  type TEXT NOT NULL CHECK(type IN ('actor','system','app','store','component','group','file','function')),
  name TEXT NOT NULL, parent TEXT, technology TEXT, description TEXT,
  tags JSON, links JSON, status TEXT, responsibilities JSON, state TEXT, PRIMARY KEY(project,id));
CREATE TABLE IF NOT EXISTS c4_connection(
  id TEXT NOT NULL, project TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL,
  name TEXT, technology TEXT, status TEXT, direction TEXT, tags TEXT, description TEXT,
  feature TEXT, interface TEXT, payload JSON, kind TEXT, PRIMARY KEY(project,id));
-- a callable contract on an object: HTTP route, function, queue, event
CREATE TABLE IF NOT EXISTS c4_interface(
  project TEXT NOT NULL, id TEXT NOT NULL, object_id TEXT NOT NULL,
  kind TEXT CHECK(kind IN ('http','function','queue','event')), name TEXT, signature TEXT,
  purpose TEXT, input TEXT, output TEXT, errors JSON, PRIMARY KEY(project,id));
CREATE TABLE IF NOT EXISTS c4_meta(
  project TEXT PRIMARY KEY, name TEXT NOT NULL, root TEXT, layout TEXT, tags JSON);
CREATE TABLE IF NOT EXISTS c4_flow(
  id TEXT NOT NULL, project TEXT NOT NULL, name TEXT, steps JSON, PRIMARY KEY(project,id));

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

-- decision text is immutable and rows undeletable, so insert sync is enough
CREATE TRIGGER IF NOT EXISTS decision_ai AFTER INSERT ON decision BEGIN
  INSERT INTO search VALUES(replace(replace(NEW.title,'đ','d'),'Đ','D'),
    replace(replace(trim(coalesce(NEW.context,'')||' '||coalesce(NEW.decision,'')||' '||coalesce(NEW.consequences,'')||' '||coalesce(NEW.rejected_options,'')),'đ','d'),'Đ','D'),
    'decision',NEW.id,NEW.project); END;

CREATE TABLE IF NOT EXISTS page(
  project TEXT NOT NULL, slug TEXT NOT NULL, title TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('research','discussion','note','plan')),
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

-- links an object to a task/issue/decision; no FK (objects are re-imported, decisions are append-only)
CREATE TABLE IF NOT EXISTS c4_link(
  project TEXT NOT NULL, object_id TEXT NOT NULL,
  ref_kind TEXT NOT NULL CHECK(ref_kind IN ('item','decision')), ref_id INTEGER NOT NULL,
  PRIMARY KEY(project,object_id,ref_kind,ref_id));
