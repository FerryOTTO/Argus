package auth

import (
	"fmt"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/llmgate/llmgate/internal/model"
)

// Claims defines the JWT claims structure
type Claims struct {
	UserID        int64  `json:"user_id"`
	Username      string `json:"username"`
	Role          string `json:"role"`
	SecurityLevel string `json:"security_level"`
	Specials      string `json:"specials"`
	jwt.RegisteredClaims
}

// GenerateToken creates a new JWT token for a user
func GenerateToken(user *model.User, secret string, expiry time.Duration) (string, error) {
	now := time.Now()
	claims := &Claims{
		UserID:        user.ID,
		Username:      user.Username,
		Role:          user.Role,
		SecurityLevel: user.SecurityLevel,
		Specials:      user.Specials,
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(expiry)),
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	tokenStr, err := token.SignedString([]byte(secret))
	if err != nil {
		return "", fmt.Errorf("failed to sign token: %w", err)
	}
	return tokenStr, nil
}

// ValidateToken parses and validates a JWT token string
func ValidateToken(tokenStr string, secret string) (*Claims, error) {
	claims := &Claims{}
	token, err := jwt.ParseWithClaims(tokenStr, claims, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(secret), nil
	})
	if err != nil {
		return nil, fmt.Errorf("failed to parse token: %w", err)
	}
	if !token.Valid {
		return nil, fmt.Errorf("invalid token")
	}
	return claims, nil
}

// RefreshToken validates an existing token and issues a new one with the same claims but new expiry
func RefreshToken(tokenStr string, secret string, expiry time.Duration) (string, error) {
	claims, err := ValidateToken(tokenStr, secret)
	if err != nil {
		return "", fmt.Errorf("failed to validate token for refresh: %w", err)
	}

	now := time.Now()
	newClaims := &Claims{
		UserID:        claims.UserID,
		Username:      claims.Username,
		Role:          claims.Role,
		SecurityLevel: claims.SecurityLevel,
		Specials:      claims.Specials,
		RegisteredClaims: jwt.RegisteredClaims{
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(expiry)),
		},
	}

	token := jwt.NewWithClaims(jwt.SigningMethodHS256, newClaims)
	newTokenStr, err := token.SignedString([]byte(secret))
	if err != nil {
		return "", fmt.Errorf("failed to sign refreshed token: %w", err)
	}
	return newTokenStr, nil
}
