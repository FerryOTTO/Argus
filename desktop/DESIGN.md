# MiMo Code Design System Specification (DESIGN.md)

This specification defines the visual language, typography, color palettes, and interaction paradigms for Clawguard Desktop, reverse-engineered and 1:1 aligned with Xiaomi MiMo Code (`mimo.xiaomi.com/zh/mimocode`).

---

## 1. Visual Theme & Color Palette

### 1.1 Dark Mode Surface (Default Theme)
- **Primary Background**: `#0B0E14` (Deep space black with subtle cool undertones)
- **Secondary Surface / Card Background**: `#121824` (Elevated dark surface)
- **Tertiary Surface / Card Highlight**: `#1A2234` (Hover & active surfaces)
- **Border Normal**: `rgba(255, 255, 255, 0.08)` / `#232B3E`
- **Border Hover**: `rgba(255, 105, 0, 0.45)` (MiMo Orange Glow)

### 1.2 Accent & Semantic Colors
- **Brand Accent (Xiaomi Orange)**:
  - Default: `#FF6900`
  - Hover / Light: `#FF8533`
  - Active / Dark: `#E05A00`
  - Subtle Tint / Background: `rgba(255, 105, 0, 0.12)`
  - Glow Shadow: `0 0 24px rgba(255, 105, 0, 0.35)`
- **Success / Secure State**:
  - Main: `#10B981` (Emerald)
  - Glow: `0 0 16px rgba(16, 185, 129, 0.28)`
- **Cyber Accent / Clearance Level**:
  - Main: `#00F2FE` / `#4FACFE` (Electric Cyan)
  - Glow: `0 0 16px rgba(0, 242, 254, 0.3)`
- **Warning / Alert**:
  - Main: `#F59E0B` (Amber)
- **Danger / Intercepted Threat**:
  - Main: `#EF4444` (Ruby Crimson)
  - Glow: `0 0 16px rgba(239, 68, 68, 0.35)`

### 1.3 Typography
- **Headings Font**: `-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif`
- **Monospace / Code Font**: `ui-monospace, SFMono-Regular, "Cascadia Code", "Fira Code", Consolas, monospace`
- **Hero Title**: Bold 36px ~ 48px, with subtle linear gradient `linear-gradient(135deg, #FFFFFF 0%, #A0AEC0 100%)`.
- **Subheading**: Regular 15px ~ 16px, color `#94A3B8`.

---

## 2. Iconic Signature Visual Effects

### 2.1 Interactive Mouse Scratch Reveal ("鼠标擦除露图")
- **Concept**: A dynamic multi-layer canvas overlay covering the hero section.
- **Base Layer**: High-contrast, glowing cyber-circuit pattern with vibrant orange and cyan traces.
- **Top Mask Layer**: Dark matte coating matching the primary background (`#0B0E14`).
- **Interaction**: As the user's cursor glides across the screen, the top mask is erased in a soft radial brush (`globalCompositeOperation = 'destination-out'`), exposing the high-tech glowing background beneath. The erased area slowly restores itself with a gentle organic decay/fade-back over 1.5 seconds.

### 2.2 Hero Subtitle Typewriter ("字幕打字机")
- **Concept**: Smooth, character-by-character typewriter loop with flashing orange cursor `|`.
- **Content Rotation**:
  1. "为 AI 智能体构筑零信任纵深防御体系"
  2. "实时阻断 .gitconfig / .env / 敏感密钥私密外泄"
  3. "四级数据密级动态分配与近永久隔离区工单流"
  4. "企业级 OpenTelemetry 遥测与高并发审计分析"

### 2.3 Bento Card Grid (`coder-card-grid`)
- **Structure**: Asymmetric 3-column / 2-row Bento layout.
- **Card Styling (`coder-card`)**:
  - Rounded corners: `rounded-2xl` (16px).
  - Background: `bg-[#121824]/80 backdrop-blur-md`.
  - Border: `border border-white/10 transition-all duration-300 ease-out`.
  - Hover Effect: `hover:border-[#FF6900]/50 hover:shadow-[0_8px_30px_rgba(255,105,0,0.12)] hover:-translate-y-1`.
  - Inner Glow: Radial gradient highlight centered on top-left of each card.

---

## 3. Component Design Tokens

### 3.1 Status Badges
- **Active / Running**: Green dot with pulsing halo (`animate-ping`) + emerald text `border border-emerald-500/30 bg-emerald-500/10`.
- **Blocked / Warning**: Red/Amber dot + text `border border-red-500/30 bg-red-500/10`.
- **Enterprise Badge**: Gradient badge `bg-gradient-to-r from-orange-500/20 to-amber-500/20 text-orange-400 border border-orange-500/30`.

### 3.2 Toggles & Switches
- **Thumb**: White circle with subtle drop shadow.
- **Track (Inactive)**: `#1E293B`.
- **Track (Active)**: `#FF6900` with subtle glow `shadow-[0_0_12px_rgba(255,105,0,0.4)]`.

### 3.3 Frameless Window Controls
- Integrated into the top-right of the custom header:
  - Minimize: `-`
  - Maximize / Restore: `□`
  - Close: `×` (Hover turns red `#EF4444`).
- Top header has `-webkit-app-region: drag` for native OS window moving, while interactive buttons have `-webkit-app-region: no-drag`.
