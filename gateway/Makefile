.PHONY: build dev dev-frontend test clean

build:
	cd web && npm install && npm run build
	go build -o bin/llmgate.exe cmd/server/main.go

dev:
	go run cmd/server/main.go -config configs/config.yaml

dev-frontend:
	cd web && npm run dev

test:
	go test ./internal/...

clean:
	rm -rf bin/
	rm -rf web/dist/
