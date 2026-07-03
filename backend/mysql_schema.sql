CREATE DATABASE IF NOT EXISTS music_hot_analysis
    DEFAULT CHARACTER SET utf8mb4
    DEFAULT COLLATE utf8mb4_unicode_ci;

USE music_hot_analysis;

CREATE TABLE IF NOT EXISTS MusicStyle (
    style_id INT AUTO_INCREMENT PRIMARY KEY,
    style_name VARCHAR(50) NOT NULL UNIQUE,
    style_desc VARCHAR(500) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Song (
    song_id INT AUTO_INCREMENT PRIMARY KEY,
    song_name VARCHAR(100) NOT NULL,
    artist_name VARCHAR(100) NOT NULL,
    album_name VARCHAR(100) NULL,
    style_id INT NULL,
    is_instrumental TINYINT(1) NOT NULL DEFAULT 0,
    CONSTRAINT uq_song_name_artist UNIQUE (song_name, artist_name),
    CONSTRAINT fk_song_style FOREIGN KEY (style_id) REFERENCES MusicStyle(style_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Artist (
    artist_id INT AUTO_INCREMENT PRIMARY KEY,
    artist_name VARCHAR(100) NOT NULL UNIQUE,
    avatar_url VARCHAR(500) NULL,
    main_style VARCHAR(50) NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS PlatformSong (
    id INT AUTO_INCREMENT PRIMARY KEY,
    song_id INT NOT NULL,
    platform VARCHAR(50) NOT NULL,
    platform_song_id VARCHAR(100) NOT NULL,
    song_url VARCHAR(500) NULL,
    cover_url VARCHAR(500) NULL,
    CONSTRAINT uq_platform_song UNIQUE (platform, platform_song_id),
    CONSTRAINT fk_platform_song_song FOREIGN KEY (song_id) REFERENCES Song(song_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS Chart (
    chart_id INT AUTO_INCREMENT PRIMARY KEY,
    platform VARCHAR(50) NOT NULL,
    chart_name VARCHAR(100) NOT NULL,
    chart_type VARCHAR(50) NULL,
    CONSTRAINT uq_platform_chart UNIQUE (platform, chart_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS ChartSong (
    id INT AUTO_INCREMENT PRIMARY KEY,
    chart_id INT NOT NULL,
    song_id INT NOT NULL,
    `rank` INT NOT NULL,
    rank_score DECIMAL(5,2) NULL,
    chart_date DATE NOT NULL,
    collect_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_chart_song_daily UNIQUE (chart_id, song_id, chart_date),
    CONSTRAINT fk_chart_song_chart FOREIGN KEY (chart_id) REFERENCES Chart(chart_id),
    CONSTRAINT fk_chart_song_song FOREIGN KEY (song_id) REFERENCES Song(song_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS SongMetric (
    metric_id INT AUTO_INCREMENT PRIMARY KEY,
    song_id INT NOT NULL,
    platform VARCHAR(50) NOT NULL,
    platform_song_id VARCHAR(100) NULL,
    play_count BIGINT NULL,
    favorite_count BIGINT NULL,
    comment_count BIGINT NULL,
    metric_date DATE NOT NULL,
    collect_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    metric_source VARCHAR(500) NULL,
    is_success TINYINT(1) NOT NULL DEFAULT 0,
    fail_reason VARCHAR(1000) NULL,
    CONSTRAINT uq_song_metric_daily UNIQUE (song_id, platform, metric_date),
    CONSTRAINT fk_song_metric_song FOREIGN KEY (song_id) REFERENCES Song(song_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS EtlLog (
    id INT AUTO_INCREMENT PRIMARY KEY,
    task_name VARCHAR(100) NOT NULL,
    platform VARCHAR(50) NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NULL,
    status VARCHAR(30) NOT NULL,
    chart_count INT NOT NULL DEFAULT 0,
    metric_count INT NOT NULL DEFAULT 0,
    error_message TEXT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS HeatScoreDaily (
    id INT AUTO_INCREMENT PRIMARY KEY,
    song_id INT NOT NULL,
    score_date DATE NOT NULL,
    netease_score DECIMAL(8,2) NOT NULL DEFAULT 0,
    qq_score DECIMAL(8,2) NOT NULL DEFAULT 0,
    kugou_score DECIMAL(8,2) NOT NULL DEFAULT 0,
    main_platform_score DECIMAL(8,2) NOT NULL DEFAULT 0,
    heat_score DECIMAL(8,2) NOT NULL DEFAULT 0,
    `rank` INT NULL,
    rank_delta INT NULL,
    trend_label VARCHAR(50) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_heat_score_daily UNIQUE (song_id, score_date),
    CONSTRAINT fk_heat_score_song FOREIGN KEY (song_id) REFERENCES Song(song_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS AiHeatAnalysis (
    id INT AUTO_INCREMENT PRIMARY KEY,
    analysis_date DATE NOT NULL,
    analysis_type VARCHAR(50) NOT NULL,
    model_name VARCHAR(100) NULL,
    prompt_version VARCHAR(50) NOT NULL DEFAULT 'v1',
    input_summary TEXT NULL,
    content TEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_ai_heat_analysis_daily UNIQUE (analysis_date, analysis_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE Artist
ADD COLUMN normalized_name VARCHAR(150) NULL UNIQUE,
ADD COLUMN canonical_name VARCHAR(100) NULL;

ALTER TABLE Chart
ADD COLUMN style_key VARCHAR(50) NULL,
ADD COLUMN style_name VARCHAR(100) NULL;

ALTER TABLE PlatformSong
ADD COLUMN platform_song_mid VARCHAR(100) NULL,
ADD COLUMN album_id VARCHAR(100) NULL,
ADD COLUMN album_mid VARCHAR(100) NULL,
ADD COLUMN song_hash VARCHAR(100) NULL,
ADD COLUMN extra_metadata TEXT NULL,
ADD COLUMN raw_song_name VARCHAR(200) NULL,
ADD COLUMN raw_artist_name VARCHAR(200) NULL,
ADD COLUMN version_type VARCHAR(50) NULL;

CREATE TABLE IF NOT EXISTS SongArtist (
    id INT AUTO_INCREMENT PRIMARY KEY,
    song_id INT NOT NULL,
    artist_id INT NOT NULL,
    role VARCHAR(30) NULL,
    sort_order INT NOT NULL DEFAULT 0,
    CONSTRAINT uq_song_artist UNIQUE (song_id, artist_id),
    CONSTRAINT fk_song_artist_song FOREIGN KEY (song_id) REFERENCES Song(song_id),
    CONSTRAINT fk_song_artist_artist FOREIGN KEY (artist_id) REFERENCES Artist(artist_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
