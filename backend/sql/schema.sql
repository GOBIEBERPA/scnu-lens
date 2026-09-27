CREATE DATABASE IF NOT EXISTS scnu_lens CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE scnu_lens;

CREATE TABLE IF NOT EXISTS crawler_sources (
  id INT AUTO_INCREMENT PRIMARY KEY,
  `key` VARCHAR(50) NOT NULL UNIQUE,
  name VARCHAR(100) NOT NULL,
  url VARCHAR(500) NOT NULL,
  parser_type VARCHAR(50) NOT NULL,
  category_hint VARCHAR(50) NOT NULL,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  last_crawled_at DATETIME NULL,
  last_fetched INT NULL,
  last_error TEXT NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS notices (
  id INT AUTO_INCREMENT PRIMARY KEY,
  source_id INT NULL,
  external_id VARCHAR(100) NOT NULL,
  source VARCHAR(100) NOT NULL,
  source_url VARCHAR(500) NOT NULL,
  title VARCHAR(500) NOT NULL,
  raw_text MEDIUMTEXT NOT NULL,
  duplicate_of INT NULL,
  deadline_date VARCHAR(10) NULL,
  open_at VARCHAR(16) NULL,
  close_at VARCHAR(16) NULL,
  structured_json JSON NULL,
  category VARCHAR(50) NOT NULL DEFAULT '기타',
  published_at DATETIME NULL,
  crawled_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  content_hash CHAR(64) NOT NULL,
  processing_status VARCHAR(20) NOT NULL DEFAULT 'raw',
  CONSTRAINT fk_notices_source FOREIGN KEY (source_id) REFERENCES crawler_sources(id) ON DELETE SET NULL,
  CONSTRAINT uq_notice_source_external UNIQUE (source_id, external_id),
  INDEX ix_notices_category_published (category, published_at),
  INDEX ix_notices_deadline_date (deadline_date),
  INDEX ix_notices_open_at (open_at),
  INDEX ix_notices_close_at (close_at),
  INDEX ix_notices_source_id (source_id),
  INDEX ix_notices_status_duplicate (processing_status, duplicate_of)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS user_profiles (
  id INT AUTO_INCREMENT PRIMARY KEY,
  web_device_id VARCHAR(100) NULL UNIQUE,
  display_name VARCHAR(100) NULL,
  department VARCHAR(100) NOT NULL DEFAULT '미설정',
  interests JSON NOT NULL,
  notify_categories JSON NOT NULL,
  push_subscription JSON NULL,
  saved_notice_ids JSON NULL,
  alert_prefs JSON NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS inbox_items (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  notice_id INT NULL,
  kind VARCHAR(20) NOT NULL,
  title VARCHAR(300) NOT NULL,
  body TEXT NOT NULL,
  url VARCHAR(300) NOT NULL DEFAULT '/',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  read_at DATETIME NULL,
  CONSTRAINT fk_inbox_user FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_inbox_notice FOREIGN KEY (notice_id) REFERENCES notices(id) ON DELETE SET NULL,
  INDEX ix_inbox_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS alarm_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  notice_id INT NOT NULL,
  `key` VARCHAR(20) NOT NULL,
  sent_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_alarm_logs_user FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_alarm_logs_notice FOREIGN KEY (notice_id) REFERENCES notices(id) ON DELETE CASCADE,
  CONSTRAINT uq_alarm_user_notice_key UNIQUE (user_id, notice_id, `key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS eval_labels (
  notice_id INT PRIMARY KEY,
  category VARCHAR(50) NOT NULL,
  deadline VARCHAR(10) NULL,
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  CONSTRAINT fk_eval_labels_notice FOREIGN KEY (notice_id) REFERENCES notices(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS briefings (
  id INT AUTO_INCREMENT PRIMARY KEY,
  user_id INT NOT NULL,
  notice_id INT NOT NULL,
  relevance_reason TEXT NOT NULL,
  delivery_status VARCHAR(30) NOT NULL DEFAULT 'pending',
  sent_at DATETIME NULL,
  reminder_sent_at DATETIME NULL,
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_briefings_user FOREIGN KEY (user_id) REFERENCES user_profiles(id) ON DELETE CASCADE,
  CONSTRAINT fk_briefings_notice FOREIGN KEY (notice_id) REFERENCES notices(id) ON DELETE CASCADE,
  CONSTRAINT uq_briefing_user_notice UNIQUE (user_id, notice_id),
  INDEX ix_briefings_notice_status (notice_id, delivery_status),
  INDEX ix_briefings_status (delivery_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

