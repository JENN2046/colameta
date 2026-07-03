USAGE_MESSAGE = """用法：
  colameta help
  colameta --version
  colameta start [managed|source-only] [project_path] [options]
  colameta stop [project_path]
  colameta restart [project_path] [options]
  colameta status [project_path] [--tunnel-admin-port PORT --tunnel-pid PID]
  colameta logs [project_path] [--lines N]
  colameta models [project_path] [--refresh]
  colameta serve <project_path> [options]
  colameta list
  colameta add <project_path> [source-only|managed]
  colameta add <project_name> <project_path> [source-only|managed]
  colameta remove <project_name|project_path>
"""

SIMPLE_START_MODES = {"source-only", "managed"}
