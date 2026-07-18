"""Runner 文件能力与路径策略规则矩阵。

集中维护 allow / deny / blocked / excluded 规则组合，供 RunnerPathPolicy 统一引用。
"""

from runner.runner_paths import project_runner_dirnames


def _runner_patterns(*suffixes: str) -> tuple[str, ...]:
    return tuple(f"{dirname}/{suffix}" for dirname in project_runner_dirnames() for suffix in suffixes)

# ---------------------------------------------------------------------------
# Allow matrix — format / capability first, legacy dir fallback second
# ---------------------------------------------------------------------------

TEXT_SOURCE_EXTENSIONS = (
    "*.html",       "**/*.html",
    "*.css",        "**/*.css",
    "*.js",         "**/*.js",
    "*.ts",         "**/*.ts",
    "*.tsx",        "**/*.tsx",
    "*.jsx",        "**/*.jsx",
    "*.vue",        "**/*.vue",
    "*.svelte",     "**/*.svelte",
    "*.astro",      "**/*.astro",
    "*.go",         "**/*.go",
    "*.php",        "**/*.php",
    "*.java",       "**/*.java",
    "*.rs",         "**/*.rs",
    "*.rb",         "**/*.rb",
    "*.cs",         "**/*.cs",
    "*.kt",         "**/*.kt",
    "*.swift",      "**/*.swift",
    "*.md",
    "*.mdx",
)

TEXT_SOURCE_ONLY_EXTENSIONS = (
    "*.py",
    "**/*.py",
)

TEXT_STATIC_ASSET_EXTENSIONS = (
    "*.svg",
    "**/*.svg",
)

PROJECT_CONFIG_FILES = (
    "README.md",
    "AGENTS.md",
    ".gitignore",
    "Makefile",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    ".editorconfig",
    ".eslintrc",
    ".eslintrc.*",
    ".prettierrc",
    ".prettierrc.*",
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "requirements.txt",
    "requirements*.txt",
    "package.json",
    "package-lock.json",
    "Package.swift",
    "Package.resolved",
    "pnpm-lock.yaml",
    "yarn.lock",
    "tsconfig.json",
    "tsconfig.*.json",
    "vite.config.*",
    "next.config.*",
    "nuxt.config.*",
    "go.mod",
    "go.sum",
    "Cargo.toml",
    "Cargo.lock",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "gradle.properties",
    "composer.json",
    "composer.lock",
    "deno.json",
    "deno.lock",
    "bun.lockb",
    "bun.lock",
    "eslint.config.*",
    "postcss.config.*",
    "tailwind.config.*",
    "svelte.config.*",
    "astro.config.*",
)

WEB_METADATA_FILES = (
    "manifest.json",
    "**/manifest.json",
    "*.webmanifest",
    "**/*.webmanifest",
    "robots.txt",
    "**/robots.txt",
    "sitemap.xml",
    "**/sitemap.xml",
    "browserconfig.xml",
    "**/browserconfig.xml",
)

COMMON_TEXT_DOC_NAMES = (
    "**/README.md",
    "**/README_EN.md",
    "**/CHANGELOG.md",
    "**/LICENSE",
    "**/LICENSE.*",
    "**/LICENSE-*",
    "**/NOTICE",
    "**/NOTICE.*",
)

GOVERNANCE_EVIDENCE_FILES = (
    "control-plane/registry/reports/*.yaml",
    "control-plane/registry/reports/**/*.yaml",
    "control-plane/registry/reports/*.md",
    "control-plane/registry/reports/**/*.md",
    "control-plane/registry/decisions/*.yaml",
    "control-plane/registry/decisions/**/*.yaml",
    "control-plane/registry/reviews/*.yaml",
    "control-plane/registry/reviews/**/*.yaml",
    "control-plane/registry/receipts/*.md",
    "control-plane/registry/receipts/**/*.md",
)

RUNNER_MANAGED_FILES = (
    *_runner_patterns(
        "plan.json",
        "todolist.json",
        "decisions.json",
        "memory.md",
        "project-context.md",
        "plans/*.yaml",
        "plans/**/*.yaml",
        "plans/*.yml",
        "plans/**/*.yml",
        "prompts/*.md",
        "prompts/**/*.md",
        "shared/*",
        "shared/**/*",
        "rules.md",
    ),
    "bin/colameta",
)

COMMIT_ONLY_BINARY_ASSET_EXTENSIONS = (
    "*.png",
    "**/*.png",
    "*.jpg",
    "**/*.jpg",
    "*.jpeg",
    "**/*.jpeg",
    "*.gif",
    "**/*.gif",
    "*.webp",
    "**/*.webp",
    "*.ico",
    "**/*.ico",
    "*.avif",
    "**/*.avif",
    "*.bmp",
    "**/*.bmp",
    "*.woff",
    "**/*.woff",
    "*.woff2",
    "**/*.woff2",
    "*.ttf",
    "**/*.ttf",
    "*.otf",
    "**/*.otf",
    "*.eot",
    "**/*.eot",
)

# Legacy directory-name-based source allow — compatibility fallback.
LEGACY_SOURCE_DIR_ALLOW = (
    "docs/*.md",
    "docs/**/*.md",
    "docs/**/*.mdx",
    "src/*",
    "src/**/*",
    "app/*",
    "app/**/*",
    "pages/*",
    "pages/**/*",
    "components/*",
    "components/**/*",
    "lib/*",
    "lib/**/*",
    "public/*",
    "public/**/*",
    "styles/*",
    "styles/**/*",
    "css/*",
    "css/**/*",
    "js/*",
    "js/**/*",
    "assets/*",
    "assets/**/*",
    "static/*",
    "static/**/*",
    "cmd/*",
    "cmd/**/*",
    "internal/*",
    "internal/**/*",
    "pkg/*",
    "pkg/**/*",
    "test/**",
    "tests/**/*",
    "tests/**/*.py",
    "__tests__/*",
    "__tests__/**/*",
    "scripts/*.py",
    "scripts/**/*.py",
    "Scripts/*",
    "Scripts/**/*",
    "adapters/*.py",
    "adapters/**/*.py",
    "schemas/*.py",
    "schemas/**/*.py",
    "runner/*.py",
    "runner/**/*.py",
    "Sources/*",
    "Sources/**/*",
    "Resources/*",
    "Resources/**/*",
)

# Legacy directory-name-based commit-only allow.
LEGACY_COMMIT_DIR_ALLOW = (
    "api/*",
    "api/**/*",
    "db/*",
    "db/**/*",
    "models/*",
    "models/**/*",
    "services/*",
    "services/**/*",
    "serverapp/*",
    "serverapp/**/*",
    "web/*",
    "web/**/*",
    "backend/*",
    "backend/**/*",
    "frontend/*",
    "frontend/**/*",
    "scripts/*",
    "scripts/**/*",
    "Scripts/*",
    "Scripts/**/*",
    "adapters/*",
    "adapters/**/*",
    "runner/*",
    "runner/**/*",
    "schemas/*",
    "schemas/**/*",
    "Sources/*",
    "Sources/**/*",
    "Resources/*",
    "Resources/**/*",
    "docs/DEV_REPORT_v*.md",
)

# ---------------------------------------------------------------------------
# Deny / blocked / excluded matrix
# ---------------------------------------------------------------------------

DENIED_SENSITIVE_PATTERNS = (
    ".git/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.pem",
    "*.key",
    "*.crt",
    "*.p12",
    "*.sqlite",
    "*.db",
    "*.log",
    "*.egg-info",
    "**/*.egg-info",
    "*.egg-info/**",
    "**/*.egg-info/**",
    ".DS_Store",
    "**/.DS_Store",
    "**/*.pyc",
)

DENIED_RUNTIME_PATTERNS = (
    *_runner_patterns(
        "logs/**",
        "runtime/**",
        "local/**",
        "state.json",
        "review-state.json",
        "settings.json",
        "runner-settings.json",
        "executor-session.json",
        "tmp/**",
        "plan-patches/**",
        "reports/**",
        "audits/**",
        "pi-session.json",
        "pi-sessions/**",
        "executor-sessions/**",
    ),
)

DENIED_GENERATED_OR_VENDOR_PATTERNS = (
    "__pycache__/**",
    ".pytest_cache/**",
    "node_modules/**",
    "dist/**",
    "build/**",
    ".build",
    ".build/**",
    "**/.build",
    "**/.build/**",
    "coverage/**",
    "venv/**",
    ".venv/**",
    "env/**",
    ".opencode/**",
    ".opencode.json",
    ".opencode.local.json",
)

COMMIT_BLOCKED_PATTERNS = (
    ".git/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "*.crt",
    "**/*.crt",
    "*.p12",
    "**/*.p12",
    "**/*secret*",
)

COMMIT_EXCLUDED_PATTERNS = (
    *_runner_patterns(
        "runtime/**",
        "logs/**",
        "reports/**",
        "audits/**",
        "local/**",
        "state.json",
        "review-state.json",
        "settings.json",
        "runner-settings.json",
        "executor-session.json",
        "tmp/**",
        "plan-patches/**",
        "pi-session.json",
        "pi-sessions/**",
        "executor-sessions/**",
    ),
    "node_modules/**",
    "dist/**",
    "build/**",
    ".build",
    ".build/**",
    "**/.build",
    "**/.build/**",
    "coverage/**",
    "venv/**",
    ".venv/**",
    "env/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".opencode/**",
    ".opencode.json",
    ".opencode.local.json",
    ".DS_Store",
    "**/.DS_Store",
    "*.pyc",
    "**/*.pyc",
    "*.sqlite",
    "**/*.sqlite",
    "*.db",
    "**/*.db",
    "*.log",
    "**/*.log",
    "*.egg-info",
    "**/*.egg-info",
    "*.egg-info/**",
    "**/*.egg-info/**",
)

DENIED_PATH_PART_NAMES = frozenset(
    {
        ".git",
        "__pycache__",
        ".pytest_cache",
        "node_modules",
        "venv",
        ".venv",
        "env",
        ".opencode",
    }
)

EXACT_ALLOWED_ROOT_FILES = frozenset(
    {
        "README.md", "AGENTS.md", ".gitignore",
        "Makefile", "Dockerfile",
        "docker-compose.yml", "docker-compose.yaml",
        ".editorconfig", ".eslintrc", ".prettierrc",
        "pyproject.toml", "setup.cfg", "setup.py",
        "requirements.txt",
        "package.json", "package-lock.json",
        "pnpm-lock.yaml", "yarn.lock",
        "tsconfig.json",
        "go.mod", "go.sum",
        "Cargo.toml", "Cargo.lock",
        "pom.xml", "build.gradle", "build.gradle.kts",
        "settings.gradle", "settings.gradle.kts", "gradle.properties",
        *_runner_patterns("plan.json", "todolist.json", "decisions.json", "memory.md", "project-context.md", "rules.md"),
        "bin/colameta",
        "manifest.json", "site.webmanifest",
        "robots.txt", "sitemap.xml", "browserconfig.xml",
        "composer.json", "composer.lock",
        "deno.json", "deno.lock",
        "bun.lockb", "bun.lock",
    }
)


def source_allowed_patterns() -> tuple[str, ...]:
    return (
        *PROJECT_CONFIG_FILES,
        *TEXT_SOURCE_EXTENSIONS,
        *TEXT_SOURCE_ONLY_EXTENSIONS,
        *LEGACY_SOURCE_DIR_ALLOW,
        *RUNNER_MANAGED_FILES,
        *COMMON_TEXT_DOC_NAMES,
        *GOVERNANCE_EVIDENCE_FILES,
        *WEB_METADATA_FILES,
        *TEXT_STATIC_ASSET_EXTENSIONS,
    )


def commit_allowed_patterns() -> tuple[str, ...]:
    return (
        *PROJECT_CONFIG_FILES,
        *TEXT_SOURCE_EXTENSIONS,
        *LEGACY_SOURCE_DIR_ALLOW,
        *RUNNER_MANAGED_FILES,
        *COMMON_TEXT_DOC_NAMES,
        *WEB_METADATA_FILES,
        *TEXT_STATIC_ASSET_EXTENSIONS,
        *COMMIT_ONLY_BINARY_ASSET_EXTENSIONS,
        *LEGACY_COMMIT_DIR_ALLOW,
    )


def denied_source_patterns() -> tuple[str, ...]:
    return (
        *DENIED_SENSITIVE_PATTERNS,
        *DENIED_GENERATED_OR_VENDOR_PATTERNS,
        *DENIED_RUNTIME_PATTERNS,
    )


def commit_blocked_patterns() -> tuple[str, ...]:
    return COMMIT_BLOCKED_PATTERNS


def commit_excluded_patterns() -> tuple[str, ...]:
    return COMMIT_EXCLUDED_PATTERNS
