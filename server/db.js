import Database from 'better-sqlite3';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const dbPath = path.resolve(__dirname, 'db', 'database.sqlite');
const db = new Database(dbPath);

db.pragma('journal_mode = WAL');

// Initial setup
db.exec(`
  CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    apiUrl TEXT NOT NULL,
    account TEXT NOT NULL,
    password TEXT NOT NULL,
    status TEXT NOT NULL,
    access_token TEXT,
    refresh_token TEXT,
    expires_in INTEGER
  );
`);

// Migration for existing tables
try {
  db.exec('ALTER TABLE clients ADD COLUMN access_token TEXT;');
  db.exec('ALTER TABLE clients ADD COLUMN refresh_token TEXT;');
  db.exec('ALTER TABLE clients ADD COLUMN expires_in INTEGER;');
} catch (e) {
  // Ignore if columns already exist
}

db.exec(`
  CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    client_id INTEGER NOT NULL,
    interval TEXT NOT NULL,
    threshold INTEGER NOT NULL,
    filters_json TEXT,
    execution_mode TEXT NOT NULL DEFAULT 'manual',
    auto_confirm BOOLEAN NOT NULL,
    active BOOLEAN NOT NULL,
    execution_status TEXT NOT NULL DEFAULT 'idle',
    total_count INTEGER NOT NULL DEFAULT 0,
    processed_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT,
    finished_at TEXT,
    last_error TEXT,
    FOREIGN KEY(client_id) REFERENCES clients(id)
  );

  CREATE TABLE IF NOT EXISTS reviews (
    id TEXT PRIMARY KEY,
    image_url TEXT NOT NULL,
    original_result TEXT NOT NULL,
    sp_name_list TEXT,
    ai_result TEXT NOT NULL,
    status TEXT NOT NULL,
    task_id INTEGER,
    task_name TEXT,
    file_id INTEGER,
    media_type TEXT,
    media_url TEXT,
    file_time TEXT,
    created_at TEXT
  );

  CREATE TABLE IF NOT EXISTS multimodal_models (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    api_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    detected_models_json TEXT,
    last_detected_at TEXT,
    created_at TEXT,
    updated_at TEXT
  );
`);

// Migration for existing tasks/reviews tables
try { db.exec("ALTER TABLE tasks ADD COLUMN execution_status TEXT NOT NULL DEFAULT 'idle';"); } catch (e) {}
try { db.exec("ALTER TABLE tasks ADD COLUMN total_count INTEGER NOT NULL DEFAULT 0;"); } catch (e) {}
try { db.exec("ALTER TABLE tasks ADD COLUMN processed_count INTEGER NOT NULL DEFAULT 0;"); } catch (e) {}
try { db.exec('ALTER TABLE tasks ADD COLUMN filters_json TEXT;'); } catch (e) {}
try { db.exec("ALTER TABLE tasks ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'manual';"); } catch (e) {}
try { db.exec('ALTER TABLE tasks ADD COLUMN started_at TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE tasks ADD COLUMN finished_at TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE tasks ADD COLUMN last_error TEXT;'); } catch (e) {}

try { db.exec('ALTER TABLE reviews ADD COLUMN task_id INTEGER;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN task_name TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN file_id INTEGER;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN sp_name_list TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN media_type TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN media_url TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN file_time TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE reviews ADD COLUMN created_at TEXT;'); } catch (e) {}

try { db.exec("ALTER TABLE multimodal_models ADD COLUMN status TEXT NOT NULL DEFAULT 'active';"); } catch (e) {}
try { db.exec('ALTER TABLE multimodal_models ADD COLUMN detected_models_json TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE multimodal_models ADD COLUMN last_detected_at TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE multimodal_models ADD COLUMN created_at TEXT;'); } catch (e) {}
try { db.exec('ALTER TABLE multimodal_models ADD COLUMN updated_at TEXT;'); } catch (e) {}

db.exec(`
  UPDATE reviews
  SET sp_name_list = original_result
  WHERE (sp_name_list IS NULL OR TRIM(sp_name_list) = '')
    AND TRIM(COALESCE(original_result, '')) != ''
    AND original_result NOT IN ('确种', '有效', '无效(空拍)', '处理中');
`);

export default db;
