package service

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"regexp"
	"strings"
)

// Skill 分发包（zip）约束：与前端上传提示、SKILL_CREATION.md 保持一致。
const (
	// SkillZipMaxBytes 上传 zip 压缩包大小上限。
	SkillZipMaxBytes = 2 << 20 // 2MB
	// SkillZipMaxTotalBytes 包内条目声明的解压总量上限（防 zip bomb）。
	SkillZipMaxTotalBytes = 16 << 20 // 16MB
	// SkillZipMaxEntries 包内条目数上限。
	SkillZipMaxEntries = 200
	// SkillMDMaxBytes 单个 SKILL.md 文件大小上限（服务端只解压该文件做摘要）。
	SkillMDMaxBytes = 512 << 10 // 512KB
	// SkillPreviewMaxChars 存入包的 SKILL.md 正文摘要截断长度。
	SkillPreviewMaxChars = 4000

	// SkillNamePattern skill 标识 = zip 顶层目录名（或 frontmatter name）。
	// 与 OpenClaw 技能目录安全命名一致：字母/数字开头，仅含 [A-Za-z0-9_-]。
	SkillNamePattern = `^[A-Za-z0-9][A-Za-z0-9_-]*$`
)

var skillNameRe = regexp.MustCompile(SkillNamePattern)

// SkillZipMeta 为上传解析结论：推导出的 skill 名、描述与 SKILL.md 摘要。
type SkillZipMeta struct {
	Name        string // skill 标识（存库唯一名）
	Description string // frontmatter description（可为空）
	ZipName     string // 上传文件名（展示用）
	ZipSize     int64  // 压缩包字节数
	Preview     string // SKILL.md 正文摘要（截断）
}

// ParseSkillZip 校验并解析上传的 skill 压缩包：
//   - 大小/条目数/解压总量受限；
//   - zip 顶层须为"单目录（目录名 = skill 名）"或"直接放置 SKILL.md"两种布局之一；
//   - SKILL.md 必存在且 ≤512KB，其 frontmatter `name`（若声明）必须与目录名一致；
//   - 服务端仅解压 SKILL.md 提取摘要，zip 原样存储、由终端侧解压安装。
func ParseSkillZip(zipName string, data []byte) (*SkillZipMeta, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("压缩包为空")
	}
	if len(data) > SkillZipMaxBytes {
		return nil, fmt.Errorf("压缩包 %d 字节超过上限 %dKB", len(data), SkillZipMaxBytes>>10)
	}
	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		return nil, fmt.Errorf("无法解析 zip：%v", err)
	}
	if len(zr.File) > SkillZipMaxEntries {
		return nil, fmt.Errorf("包内条目 %d 超过上限 %d", len(zr.File), SkillZipMaxEntries)
	}

	meta := &SkillZipMeta{ZipName: zipName, ZipSize: int64(len(data))}

	// ── 第一遍：识别顶层布局（过滤打包垃圾后） ──
	topFiles := map[string]bool{} // 顶层文件名
	topDirs := map[string]bool{}  // 顶层目录名
	var all []*zip.File           // 有效条目
	for _, f := range zr.File {
		if isZipNoise(f.Name) {
			continue
		}
		if f.FileInfo().IsDir() {
			if seg := firstSegment(f.Name); seg != "" {
				topDirs[seg] = true
			}
			continue
		}
		parts := strings.SplitN(f.Name, "/", 2)
		if len(parts) == 1 {
			topFiles[parts[0]] = true
		} else {
			topDirs[parts[0]] = true
		}
		all = append(all, f)
	}
	if len(all) == 0 {
		return nil, fmt.Errorf("压缩包内没有任何文件")
	}

	root := ""
	switch {
	case topFiles["SKILL.md"]:
		// 布局 A：顶层仅放一个 SKILL.md（skill 名取自 frontmatter name）
		if len(topFiles) != 1 || len(topDirs) != 0 {
			return nil, fmt.Errorf("顶层直接放置 SKILL.md 时不能附带其它文件或目录，请统一为单目录结构")
		}
	default:
		// 布局 B：单目录（目录名 = skill 名）
		if len(topDirs) != 1 || len(topFiles) > 0 {
			return nil, fmt.Errorf("压缩包顶层须为单个目录（目录名 = skill 名），或将仅一个 SKILL.md 直接放在顶层")
		}
		for d := range topDirs {
			root = d
		}
		if !skillNameRe.MatchString(root) {
			return nil, fmt.Errorf("skill 目录名 %q 不合法：须以字母/数字开头，仅含 [A-Za-z0-9_-]", root)
		}
	}

	// ── 第二遍：总量校验 + 定位 SKILL.md ──
	var total uint64
	var skillEntry *zip.File
	for _, f := range all {
		total += f.UncompressedSize64
		if total > SkillZipMaxTotalBytes {
			return nil, fmt.Errorf("包内内容约 %dKB，超过解压总量上限 %dMB", total>>10, SkillZipMaxTotalBytes>>20)
		}
		rel := relativeToRoot(f.Name, root)
		if rel == "SKILL.md" && skillEntry == nil {
			skillEntry = f
		}
	}
	if skillEntry == nil {
		return nil, fmt.Errorf("未找到 SKILL.md，压缩包不符合 skill 规范（见 SKILL_CREATION.md）")
	}
	if skillEntry.UncompressedSize64 > SkillMDMaxBytes {
		return nil, fmt.Errorf("SKILL.md %dKB 超过上限 %dKB", skillEntry.UncompressedSize64>>10, SkillMDMaxBytes>>10)
	}

	// ── 第三遍：读取 SKILL.md → frontmatter 命名/描述 + 摘要 ──
	rc, err := skillEntry.Open()
	if err != nil {
		return nil, fmt.Errorf("无法读取 SKILL.md：%v", err)
	}
	defer rc.Close()
	body, err := io.ReadAll(io.LimitReader(rc, SkillMDMaxBytes+1))
	if err != nil {
		return nil, fmt.Errorf("无法读取 SKILL.md：%v", err)
	}
	if len(body) > SkillMDMaxBytes {
		return nil, fmt.Errorf("SKILL.md 超过上限 %dKB", SkillMDMaxBytes>>10)
	}

	frontName, frontDesc := parseSkillFrontmatter(body)
	if root == "" {
		root = frontName
		if root == "" {
			return nil, fmt.Errorf("SKILL.md 直接置于顶层时，frontmatter 必须声明 name（见 SKILL_CREATION.md）")
		}
		if !skillNameRe.MatchString(root) {
			return nil, fmt.Errorf("frontmatter name %q 不合法：须以字母/数字开头，仅含 [A-Za-z0-9_-]", root)
		}
	} else if frontName != "" && frontName != root {
		return nil, fmt.Errorf("frontmatter name %q 与目录名 %q 不一致（须一致）", frontName, root)
	}

	meta.Name = root
	meta.Description = frontDesc
	meta.Preview = truncatePreview(string(body))
	return meta, nil
}

// relativeToRoot 返回条目相对 skill 根（root="" 即顶层）的路径。
func relativeToRoot(name, root string) string {
	if root == "" {
		return name
	}
	return strings.TrimPrefix(name, root+"/")
}

// firstSegment 返回路径首个段（目录名去尾斜杠）。
func firstSegment(name string) string {
	return strings.SplitN(strings.TrimSuffix(name, "/"), "/", 2)[0]
}

// isZipNoise 过滤打包产物垃圾条目（macOS/常见工具生成）。
func isZipNoise(name string) bool {
	trimmed := strings.TrimSuffix(name, "/")
	if trimmed == "__MACOSX" || strings.HasPrefix(trimmed, "__MACOSX/") {
		return true
	}
	base := trimmed
	if i := strings.LastIndex(trimmed, "/"); i >= 0 {
		base = trimmed[i+1:]
	}
	return base == ".DS_Store" || base == "Thumbs.db"
}

// parseSkillFrontmatter 极简解析 SKILL.md 的 YAML frontmatter（--- 起止），
// 提取 name/description；无 frontmatter 或字段缺失时返回空串。
func parseSkillFrontmatter(body []byte) (name, description string) {
	s := string(body)
	if !strings.HasPrefix(s, "---") {
		return "", ""
	}
	rest := strings.TrimLeft(strings.TrimPrefix(s, "---"), "\r\n")
	end := strings.Index(rest, "\n---")
	if end < 0 {
		return "", ""
	}
	for _, line := range strings.Split(rest[:end], "\n") {
		line = strings.TrimSpace(line)
		if strings.HasPrefix(line, "name:") {
			name = strings.TrimSpace(strings.TrimPrefix(line, "name:"))
		} else if strings.HasPrefix(line, "description:") {
			description = strings.TrimSpace(strings.TrimPrefix(line, "description:"))
		}
	}
	return name, description
}

// truncatePreview 截取 SKILL.md 正文前 N 字符做摘要（保留原始换行观感）。
func truncatePreview(s string) string {
	if len(s) <= SkillPreviewMaxChars {
		return s
	}
	return s[:SkillPreviewMaxChars] + "\n…（摘要截断）"
}
