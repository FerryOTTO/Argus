package config

import (
	"fmt"
	"os"
	"time"

	"gopkg.in/yaml.v3"
)

type Config struct {
	Server       ServerConfig       `yaml:"server"`
	Database     DatabaseConfig     `yaml:"database"`
	Log          LogConfig          `yaml:"log"`
	Audit        AuditConfig        `yaml:"audit"`
	Conversation ConversationConfig `yaml:"conversation"`
	Security     SecurityConfig     `yaml:"security"`
}

type ServerConfig struct {
	Port        int           `yaml:"port"`
	JWTSecret   string        `yaml:"jwt_secret"`
	JWTExpiry   time.Duration `yaml:"jwt_expiry"`
	CORSOrigins []string      `yaml:"cors_origins"`
}

type DatabaseConfig struct {
	Path string `yaml:"path"`
}

type LogConfig struct {
	Level string `yaml:"level"`
}

type AuditConfig struct {
	RetentionDays int `yaml:"retention_days"`
	BatchSize     int `yaml:"batch_size"`
}

type ConversationConfig struct {
	RetentionDays int `yaml:"retention_days"`
	BatchSize     int `yaml:"batch_size"`
}

type SecurityConfig struct {
	EncryptKey     string        `yaml:"encrypt_key"`
	LoginMaxRetries int          `yaml:"login_max_retries"`
	LockoutDuration time.Duration `yaml:"lockout_duration"`
}

// Load reads the configuration from the given path and applies environment variable overrides
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("failed to read config file: %w", err)
	}

	cfg := &Config{}
	if err := yaml.Unmarshal(data, cfg); err != nil {
		return nil, fmt.Errorf("failed to parse config file: %w", err)
	}

	// Apply environment variable overrides
	if port := os.Getenv("LLMGATE_SERVER_PORT"); port != "" {
		var p int
		if _, err := fmt.Sscanf(port, "%d", &p); err == nil {
			cfg.Server.Port = p
		}
	}

	if dbPath := os.Getenv("LLMGATE_DATABASE_PATH"); dbPath != "" {
		cfg.Database.Path = dbPath
	}

	if jwtSecret := os.Getenv("LLMGATE_JWT_SECRET"); jwtSecret != "" {
		cfg.Server.JWTSecret = jwtSecret
	}

	if logLevel := os.Getenv("LLMGATE_LOG_LEVEL"); logLevel != "" {
		cfg.Log.Level = logLevel
	}

	if err := cfg.Validate(); err != nil {
		return nil, err
	}

	return cfg, nil
}

// Validate checks that all required configuration fields are present
func (c *Config) Validate() error {
	if c.Server.Port == 0 {
		return fmt.Errorf("server port is required")
	}

	if c.Server.JWTSecret == "" {
		return fmt.Errorf("jwt_secret is required")
	}

	if c.Database.Path == "" {
		return fmt.Errorf("database path is required")
	}

	if c.Log.Level == "" {
		c.Log.Level = "info"
	}

	if c.Audit.RetentionDays == 0 {
		c.Audit.RetentionDays = 90
	}

	if c.Audit.BatchSize == 0 {
		c.Audit.BatchSize = 1024
	}

	if c.Conversation.RetentionDays == 0 {
		c.Conversation.RetentionDays = 90
	}

	if c.Conversation.BatchSize == 0 {
		c.Conversation.BatchSize = 16
	}

	if c.Security.LoginMaxRetries == 0 {
		c.Security.LoginMaxRetries = 5
	}

	if c.Security.LockoutDuration == 0 {
		c.Security.LockoutDuration = 15 * time.Minute
	}

	return nil
}
