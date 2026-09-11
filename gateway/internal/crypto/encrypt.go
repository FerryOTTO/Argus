package crypto

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"io"
)

// Encryptor provides AES-GCM encryption and decryption
type Encryptor struct {
	aead cipher.AEAD
}

// NewEncryptor creates a new Encryptor from a config key.
// If key is empty, returns nil (plaintext mode for backward compatibility).
// The key is hashed with SHA-256 to ensure correct AES key size.
func NewEncryptor(key string) (*Encryptor, error) {
	if key == "" {
		return nil, nil
	}

	// Hash the key to get a consistent 32-byte AES-256 key
	hash := sha256.Sum256([]byte(key))

	block, err := aes.NewCipher(hash[:])
	if err != nil {
		return nil, err
	}

	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, err
	}

	return &Encryptor{aead: aead}, nil
}

// Encrypt encrypts plaintext using AES-GCM and returns base64-encoded ciphertext.
// If encryptor is nil (empty key), returns plaintext unchanged.
func (e *Encryptor) Encrypt(plaintext string) (string, error) {
	if e == nil {
		return plaintext, nil
	}

	nonce := make([]byte, e.aead.NonceSize())
	if _, err := io.ReadFull(rand.Reader, nonce); err != nil {
		return "", err
	}

	ciphertext := e.aead.Seal(nonce, nonce, []byte(plaintext), nil)
	return base64.StdEncoding.EncodeToString(ciphertext), nil
}

// Decrypt decrypts base64-encoded ciphertext using AES-GCM.
// If encryptor is nil (empty key), returns the input unchanged.
func (e *Encryptor) Decrypt(encoded string) (string, error) {
	if e == nil {
		return encoded, nil
	}

	data, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return "", errors.New("invalid encrypted data format")
	}

	nonceSize := e.aead.NonceSize()
	if len(data) < nonceSize {
		return "", errors.New("ciphertext too short")
	}

	nonce, ciphertext := data[:nonceSize], data[nonceSize:]
	plaintext, err := e.aead.Open(nil, nonce, ciphertext, nil)
	if err != nil {
		return "", errors.New("decryption failed: invalid key or corrupted data")
	}

	return string(plaintext), nil
}
