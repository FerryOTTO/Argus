package model

import "time"

type User struct {
	ID                 int64     `db:"id" json:"id"`
	Username           string    `db:"username" json:"username"`
	PasswordHash       string    `db:"password_hash" json:"-"`
	Email              *string   `db:"email" json:"email,omitempty"`
	Role               string    `db:"role" json:"role"`
	IsActive           bool      `db:"is_active" json:"is_active"`
	MustChangePassword bool      `db:"must_change_password" json:"must_change_password"`
	// Argus 身份方案（011_identity.sql）：
	// security_level 取值 public/internal/secret/top_secret，与 access_control 对齐；
	// specials 为服务端权威特例写法，下发 access_user 写入终端 bound_user，不再写本地 users.txt。
	SecurityLevel string `db:"security_level" json:"security_level"`
	Specials      string `db:"specials" json:"specials"`
	CreatedAt      time.Time `db:"created_at" json:"created_at"`
	UpdatedAt      time.Time `db:"updated_at" json:"updated_at"`
}
