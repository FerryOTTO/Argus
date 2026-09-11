package crypto

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
)

// GenerateSecret returns a cryptographically random 64-hex-char secret
// (32 random bytes). Used for terminal registration codes and telemetry tokens.
func GenerateSecret() (string, error) {
	buf := make([]byte, 32)
	if _, err := rand.Read(buf); err != nil {
		return "", err
	}
	return hex.EncodeToString(buf), nil
}

// HashSecret returns the SHA-256 hex digest of a secret.
// Only digests are persisted so a database leak does not expose live tokens.
func HashSecret(secret string) string {
	sum := sha256.Sum256([]byte(secret))
	return hex.EncodeToString(sum[:])
}
