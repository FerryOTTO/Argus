package store

import (
	"database/sql"
	"fmt"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/llmgate/llmgate/internal/model"
)

// UserStore handles user database operations
type UserStore struct {
	db *sqlx.DB
}

// NewUserStore creates a new UserStore
func NewUserStore(db *sqlx.DB) *UserStore {
	return &UserStore{db: db}
}

// Create inserts a new user and returns it with the auto-generated ID
func (s *UserStore) Create(user *model.User) error {
	now := time.Now()
	user.CreatedAt = now
	user.UpdatedAt = now

	query := `
		INSERT INTO users (username, password_hash, email, role, is_active, must_change_password, security_level, specials, created_at, updated_at)
		VALUES (:username, :password_hash, :email, :role, :is_active, :must_change_password, :security_level, :specials, :created_at, :updated_at)
	`
	result, err := s.db.NamedExec(query, user)
	if err != nil {
		return fmt.Errorf("failed to create user: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return fmt.Errorf("failed to get last insert id: %w", err)
	}
	user.ID = id

	return nil
}

// GetByID retrieves a user by ID
func (s *UserStore) GetByID(id int64) (*model.User, error) {
	var user model.User
	query := `SELECT * FROM users WHERE id = ?`
	if err := s.db.Get(&user, query, id); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get user by id: %w", err)
	}
	return &user, nil
}

// GetByUsername retrieves a user by username
func (s *UserStore) GetByUsername(username string) (*model.User, error) {
	var user model.User
	query := `SELECT * FROM users WHERE username = ?`
	if err := s.db.Get(&user, query, username); err != nil {
		if err == sql.ErrNoRows {
			return nil, nil
		}
		return nil, fmt.Errorf("failed to get user by username: %w", err)
	}
	return &user, nil
}

// List returns a paginated list of users with total count
func (s *UserStore) List(page, pageSize int) ([]model.User, int, error) {
	var users []model.User
	var total int

	// Get total count
	countQuery := `SELECT COUNT(*) FROM users`
	if err := s.db.Get(&total, countQuery); err != nil {
		return nil, 0, fmt.Errorf("failed to count users: %w", err)
	}

	// Get paginated results
	offset := (page - 1) * pageSize
	query := `SELECT * FROM users ORDER BY id LIMIT ? OFFSET ?`
	if err := s.db.Select(&users, query, pageSize, offset); err != nil {
		return nil, 0, fmt.Errorf("failed to list users: %w", err)
	}

	return users, total, nil
}

// Update updates user fields (role, email, is_active, security_level, specials)
func (s *UserStore) Update(user *model.User) error {
	user.UpdatedAt = time.Now()
	query := `
		UPDATE users
		SET role = :role, email = :email, is_active = :is_active,
		    security_level = :security_level, specials = :specials, updated_at = :updated_at
		WHERE id = :id
	`
	result, err := s.db.NamedExec(query, user)
	if err != nil {
		return fmt.Errorf("failed to update user: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("user not found")
	}

	return nil
}

// UpdatePassword updates the password hash for a user
func (s *UserStore) UpdatePassword(id int64, passwordHash string) error {
	query := `UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, passwordHash, time.Now(), id)
	if err != nil {
		return fmt.Errorf("failed to update password: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("user not found")
	}

	return nil
}

// SetMustChangePassword updates the must_change_password flag for a user
func (s *UserStore) SetMustChangePassword(id int64, mustChange bool) error {
	query := `UPDATE users SET must_change_password = ?, updated_at = ? WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, mustChange, time.Now(), id)
	if err != nil {
		return fmt.Errorf("failed to update must_change_password: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("user not found")
	}

	return nil
}

// Delete performs a soft delete by setting is_active to 0
func (s *UserStore) Delete(id int64) error {
	query := `UPDATE users SET is_active = 0, updated_at = ? WHERE id = ?`
	result, err := ExecWithRetry(s.db, query, time.Now(), id)
	if err != nil {
		return fmt.Errorf("failed to delete user: %w", err)
	}

	rows, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("failed to get rows affected: %w", err)
	}
	if rows == 0 {
		return fmt.Errorf("user not found")
	}

	return nil
}
