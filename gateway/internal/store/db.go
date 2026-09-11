package store

import (
	"database/sql"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/jmoiron/sqlx"
	_ "modernc.org/sqlite"
)

// DBWriteMu serializes write operations across different stores
// to prevent SQLITE_BUSY errors from concurrent SQLite writers.
var DBWriteMu sync.Mutex

// Open opens a SQLite database at the given path with optimal settings
func Open(dbPath string) (*sqlx.DB, error) {
	// Ensure data directory exists
	dir := filepath.Dir(dbPath)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create data directory: %w", err)
	}

	db, err := sqlx.Open("sqlite", dbPath)
	db.SetMaxOpenConns(1)
	db.SetMaxIdleConns(1)
	db.SetConnMaxLifetime(0)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Set PRAGMA options for optimal performance
	if _, err := db.Exec("PRAGMA journal_mode=WAL"); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to set WAL mode: %w", err)
	}

	if _, err := db.Exec("PRAGMA busy_timeout=5000"); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to set busy_timeout: %w", err)
	}

	if _, err := db.Exec("PRAGMA foreign_keys=ON"); err != nil {
		db.Close()
		return nil, fmt.Errorf("failed to enable foreign keys: %w", err)
	}

	return db, nil
}

// RunMigrations reads SQL files from the migrations directory and executes them in order.
// It tracks applied migrations in a schema_migrations table to avoid re-running.
func RunMigrations(db *sqlx.DB, migrationsDir string) error {
	// Create migration tracking table
	if _, err := db.Exec(`CREATE TABLE IF NOT EXISTS schema_migrations (
		name TEXT PRIMARY KEY,
		applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
	)`); err != nil {
		return fmt.Errorf("failed to create schema_migrations table: %w", err)
	}

	entries, err := os.ReadDir(migrationsDir)
	if err != nil {
		return fmt.Errorf("failed to read migrations directory %q: %w", migrationsDir, err)
	}

	// Sort migration files by name
	sort.Slice(entries, func(i, j int) bool {
		return entries[i].Name() < entries[j].Name()
	})

	for _, entry := range entries {
		if entry.IsDir() || !strings.HasSuffix(entry.Name(), ".sql") {
			continue
		}

		name := entry.Name()

		// Check if already applied
		var count int
		if err := db.Get(&count, "SELECT COUNT(*) FROM schema_migrations WHERE name = ?", name); err != nil {
			return fmt.Errorf("failed to check migration status %s: %w", name, err)
		}
		if count > 0 {
			continue // already applied
		}

		content, err := os.ReadFile(filepath.Join(migrationsDir, name))
		if err != nil {
			return fmt.Errorf("failed to read migration file %s: %w", name, err)
		}

		if _, err := db.Exec(string(content)); err != nil {
			return fmt.Errorf("failed to execute migration %s: %w", name, err)
		}

		// Record as applied
		if _, err := db.Exec("INSERT INTO schema_migrations (name) VALUES (?)", name); err != nil {
			return fmt.Errorf("failed to record migration %s: %w", name, err)
		}

		fmt.Printf("Applied migration: %s\n", name)
	}

	return nil
}

func IsBusyError(err error) bool {
	if err == nil {
		return false
	}
	msg := err.Error()
	return strings.Contains(msg, "SQLITE_BUSY") || strings.Contains(msg, "database is locked")
}

func ExecWithRetry(db *sqlx.DB, query string, args ...interface{}) (sql.Result, error) {
	var last error
	wait := 20 * time.Millisecond
	for i := 0; i < 5; i++ {
		res, e := db.Exec(query, args...)
		if e == nil { return res, nil }
		last = e
		if !IsBusyError(e) { return nil, e }
		time.Sleep(wait)
		wait *= 2
	}
	return nil, last
}
