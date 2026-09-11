package static

import (
	"io/fs"
	"net/http"

	"github.com/gin-gonic/gin"
	"github.com/llmgate/llmgate/web"
)

// indexHTML holds the content of index.html for SPA fallback
var indexHTML []byte

// SetupStatic serves the frontend from the embedded filesystem.
func SetupStatic(r *gin.Engine, fallback string) {
	distFS, err := fs.Sub(web.DistFS, "dist")
	if err != nil {
		return
	}

	// Pre-load index.html for SPA fallback
	indexHTML, err = fs.ReadFile(distFS, "index.html")
	if err != nil {
		return
	}

	fsWrapper := http.FS(distFS)

	// Serve /assets/* from embedded dist/assets
	assetsFS, err := fs.Sub(distFS, "assets")
	if err == nil {
		r.StaticFS("/assets", http.FS(assetsFS))
	}

	// Serve favicon.ico (fall back to vite.svg: web/dist ships without favicon.ico,
	// and index.html already references /vite.svg as icon)
	r.GET("/favicon.ico", func(c *gin.Context) {
		if f, err := distFS.Open("favicon.ico"); err == nil {
			f.Close()
			c.FileFromFS("favicon.ico", fsWrapper)
			return
		}
		c.FileFromFS("vite.svg", fsWrapper)
	})

	// Serve root
	r.GET("/", func(c *gin.Context) {
		c.Data(http.StatusOK, "text/html; charset=utf-8", indexHTML)
	})

	// SPA fallback: serve index.html for any unmatched route
	r.NoRoute(func(c *gin.Context) {
		path := c.Request.URL.Path

		// Return JSON 404 for API and v1 proxy routes
		if len(path) >= 4 && (path[:4] == "/v1/" || path[:4] == "/api") {
			c.JSON(http.StatusNotFound, gin.H{
				"error": gin.H{
					"message": "endpoint not found",
					"type":    "not_found_error",
				},
			})
			return
		}

		// Try to serve the exact file from embedded FS
		filePath := path[1:] // strip leading /
		if f, err := distFS.Open(filePath); err == nil {
			stat, _ := f.Stat()
			if stat != nil && !stat.IsDir() {
				f.Close()
				c.FileFromFS(filePath, fsWrapper)
				return
			}
			f.Close()
		}

		// Serve index.html for SPA client-side routing
		c.Data(http.StatusOK, "text/html; charset=utf-8", indexHTML)
	})
}
